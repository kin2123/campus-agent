"""Agent 对话接口（SSE 流式 + 人工审批）。

## 为什么要用 SSE 而不是 WebSocket

Agent 的过程是「单向、有明确终点的推进」：思考 → 调工具 → 再思考 → 回答。
不需要双向实时通信，SSE 更简单、能复用 HTTP 鉴权、断线可重连。

## 前端为什么不能用原生 EventSource

`EventSource` **无法携带 `Authorization` 请求头** —— 这是浏览器的硬限制，
不是配置问题。所以前端必须用 `fetch` + `ReadableStream` 手工解析 SSE 帧
（见 frontend/src/api/sse.js）。

## 短票据的签发点就在这里

`/api/agent/chat` 拿到的是浏览器的正式票据（12 小时有效）。
在建立 MCP 连接前，这里会**换成一张 5 分钟有效的短票据**，
再放进 MCP 请求头。这样：
- 即使短票据泄漏，影响窗口也只有 5 分钟
- 模型全程看不到任何票据内容
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import PendingAction, User
from ..schemas import ChatRequest, ResumeRequest
from ..security import create_mcp_ticket
from ..services import write_audit
from ..agent.ledger import ResumeLedger, record_pending_actions
from ..agent.llm import describe_provider
from ..agent.runtime import (
    build_agent,
    get_state,
    stream_chat,
    stream_resume,
)
from ..agent.session import thread_key

router = APIRouter(prefix="/api/agent", tags=["Agent"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # 让 nginx 之类的反代不要缓冲，否则流式会变成一次性返回
    "X-Accel-Buffering": "no",
}


@router.get("/status", summary="Agent 与 MCP 连通性自检")
async def status(user: User = Depends(get_current_user)) -> dict:
    """把「模型是什么」「MCP 连不连得上」「哪些工具要审批」一次看清。"""
    provider = describe_provider()
    ticket = create_mcp_ticket(user.id, user.username, user.role)
    result: dict = {"model": provider, "user": user.username}
    try:
        _agent, meta = await build_agent(ticket)
        result["mcp"] = {"connected": True, **meta}
    except Exception as exc:  # noqa: BLE001
        result["mcp"] = {
            "connected": False,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "请确认 MCP 工具服务已在 18001 端口启动。",
        }
    return result


@router.post("/chat", summary="与 Agent 对话（SSE）")
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    thread_id = thread_key(user.id, payload.thread_id)

    # 正式票据 -> 短票据。身份从此走带外通道，不再经过模型。
    ticket = create_mcp_ticket(user.id, user.username, user.role)

    # 状态必须从编译后的图读取；先建 Agent 才能调用 aget_state。
    try:
        agent, meta = await build_agent(ticket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=(
                f"建立 Agent 失败：{type(exc).__name__}: {exc}。"
                "请确认 MCP 工具服务（18001）已启动。"
            ),
        ) from exc

    # 同一会话还有待审批操作时，不允许继续发消息：
    # 否则会创建新的中断、留下无法对账的 pending 台账。
    if payload.thread_id:
        state = await get_state(agent, thread_id)
        if state.get("error"):
            raise HTTPException(status_code=503, detail="读取会话状态失败，请稍后重试")
        if state.get("exists") and state.get("has_interrupt"):
            raise HTTPException(
                status_code=409,
                detail="当前会话还有待审批操作，请先批准或拒绝后再继续",
            )

    write_audit(
        db,
        user=user,
        action="agent_chat",
        target_type="thread",
        target_id=thread_id,
        detail={"message": payload.message[:200]},
        source="AI",
        message="用户向 Agent 发起对话",
    )

    async def generator() -> AsyncIterator[str]:
        from ..agent.runtime import sse as make_sse

        # 把工具清单先发给前端，让界面能显示「本次可用工具」
        yield make_sse("meta", {"thread_id": thread_id, **meta})

        async for frame in stream_chat(agent, payload.message, thread_id):
            # 一旦出现审批中断，就把待审批的操作落台账。
            # 用独立 session：请求级的 session 在流式响应期间已经关闭了。
            if frame.startswith("event: interrupt"):
                record_pending_actions(thread_id, user.id, frame)
            yield frame

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/resume", summary="审批后恢复执行（SSE）")
async def resume(
    payload: ResumeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    # thread 必须落在当前用户命名空间里：客户端传来的 id 不能直接当授权凭据。
    thread_id = thread_key(user.id, payload.thread_id)
    ticket = create_mcp_ticket(user.id, user.username, user.role)

    # 先确认 Agent 真的能建起来，再落用户决定。
    # 否则 MCP 不可用时台账已变成 approved/rejected，而图里仍停在中断，
    # 重试时会因「没有 pending 行」失去数量校验和结果回填的依据。
    try:
        agent, _meta = await build_agent(ticket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=(
                f"Agent 未就绪，审批未执行：{type(exc).__name__}: {exc}。"
                "请确认 MCP 工具服务（18001）已启动后重试。"
            ),
        ) from exc

    state = await get_state(agent, thread_id)
    if state.get("error"):
        raise HTTPException(status_code=503, detail="读取会话状态失败，请稍后重试")
    if not state.get("exists"):
        raise HTTPException(
            status_code=409, detail="会话不存在或已结束，请重新发起对话"
        )
    if not state.get("has_interrupt"):
        raise HTTPException(status_code=409, detail="当前会话没有待审批操作")

    # 逐项决定：顺序必须与 interrupt 事件里的 actions 一致。
    decisions = [
        {"type": d.type}
        if d.type == "approve" or not d.message
        else {"type": d.type, "message": d.message}
        for d in payload.decisions
    ]

    pending = (
        db.query(PendingAction)
        .filter(
            PendingAction.thread_id == thread_id,
            PendingAction.user_id == user.id,
            PendingAction.status == "pending",
        )
        .order_by(PendingAction.id)
        .all()
    )
    if pending and len(decisions) != len(pending):
        raise HTTPException(
            status_code=400,
            detail=(
                f"有 {len(pending)} 个待审批操作，但收到 {len(decisions)} 个决定；"
                "请为每个操作分别选择批准或拒绝"
            ),
        )

    approved_count = sum(1 for d in decisions if d["type"] == "approve")
    rejected_count = len(decisions) - approved_count
    now = datetime.now(timezone.utc)

    # 第一段审计：用户做了什么决定。真正的执行结果由 ResumeLedger 回填。
    write_audit(
        db,
        user=user,
        action="agent_approval",
        target_type="thread",
        target_id=thread_id,
        detail={
            "decisions": decisions,
            "actions": [
                {"tool_name": r.tool_name, "args": r.args} for r in pending
            ],
        },
        source="AI",
        result="SUCCESS" if approved_count else "REJECTED",
        message=(
            f"用户对 {len(pending)} 个写操作做出决定："
            f"批准 {approved_count} 个、拒绝 {rejected_count} 个"
        ),
    )

    approved_rows: list[tuple[int, str]] = []
    for row, decision in zip(pending, decisions):
        row.decided_at = now
        if decision["type"] == "approve":
            # 先记「已批准」，result 留空；等工具真正返回后再落最终结果。
            row.status = "approved"
            row.result = None
            row.error = None
            approved_rows.append((row.id, row.tool_name))
        else:
            row.status = "rejected"
            row.result = "REJECTED"
            row.error = None
    db.commit()

    ledger = ResumeLedger(thread_id, user.id)
    ledger.track_approved(approved_rows)

    async def generator() -> AsyncIterator[str]:
        from ..agent.runtime import sse as make_sse

        try:
            async for frame in stream_resume(
                agent,
                decisions,
                thread_id,
                [row.tool_name for row in pending],
            ):
                ledger.on_event(frame)
                # resume 过程中模型可能再次触发写操作中断，也要进台账。
                if frame.startswith("event: interrupt"):
                    record_pending_actions(thread_id, user.id, frame)
                yield frame
        finally:
            ledger.flush()

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/tools", summary="查看 Agent 可见工具与审批策略")
async def tools(user: User = Depends(get_current_user)) -> dict:
    """安全检查项：工具的 schema 是否完整、有没有身份字段混进参数。"""
    ticket = create_mcp_ticket(user.id, user.username, user.role)
    try:
        _agent, meta = await build_agent(ticket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"MCP 不可用：{exc}") from exc

    items = meta.get("tool_details", [])
    return {
        "meta": {k: v for k, v in meta.items() if k != "tool_details"},
        "summary": {
            "total": len(items),
            "read": sum(1 for t in items if not t["is_write"]),
            "write": sum(1 for t in items if t["is_write"]),
            "empty_description": [
                t["name"] for t in items if t["description_length"] == 0
            ],
            "identity_leaks": [t["name"] for t in items if t["has_identity_param"]],
        },
        "tools": items,
    }
