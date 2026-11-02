"""Agent 运行时：MCP 客户端 + create_agent 编排 + SSE 事件流 + 人工审批。

## 生命周期：为什么 Agent 要每个请求重建

`MultiServerMCPClient` 的 `headers` 是**构造时静态的**。短票据按用户、按会话不同，
如果复用同一个 client 实例，后一个用户的请求会带着前一个用户的票据 —— 直接串号。

所以：**每次请求新建 client、重新拉工具、重建 agent**。
代价是每次多一轮 MCP 握手（本地进程间调用，实测毫秒级），换的是身份绝不串号。

**但 checkpointer 必须是全局单例**，否则审批中断后无法用同一 thread_id 恢复
（中断状态存在 checkpointer 里，不在 agent 实例里）。

## 四条安全底线

1. **身份带外透传**：user_id 不出现在任何工具参数里，只走 HTTP 头
2. **只拦写工具**：读工具不登记审批，误拦率为 0
3. **拒绝即无副作用**：拒绝审批后不落库，且业务表条数不变（可被评测验证）
4. **会话按用户隔离**：thread_id 统一加 `u<user_id>:` 前缀，
   续写会话和审批中断都只能作用于本人（见 session.py）
"""
from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ToolCallLimitMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ..config import settings
from .llm import build_model, describe_provider
from .policy import audit_tool_names, build_interrupt_on, is_write_tool
from .state import snapshot_info
from .text import content_to_text

# 中断状态存在这里。必须全局单例 —— resume 时要能找到同一个 thread。
_CHECKPOINTER = InMemorySaver()

SYSTEM_PROMPT = """你是校园课程智能助手，为本校学生提供课程与教务相关的帮助。

## 你能做的事
- 查询课程列表、余量、课程详情
- 查询「当前登录学生本人」的课表和已出成绩
- 检索学校规章制度（培养方案、选课规则、考试规定、奖惩办法等）
- 帮学生选课 / 退课（执行前会弹出确认，学生同意后才真正执行）

## 必须遵守的规则

1. **涉及制度、规则、流程的问题，一律先查知识库再回答**，不要凭常识推测。
   例如「一学期最多选多少学分」「缓考怎么申请」「作弊怎么处理」。
   回答时说明依据来自哪份文件。
2. **只根据自己的工具返回的数据回答**。工具没查到就说没查到，
   绝不编造分数、名额、时间、金额等任何具体数字。
3. **你没有的能力要明确说没有**：修改成绩、重置密码、办理缓考/免修、
   替学生考试等。这些都要走线下人工流程。请直接说明并给出正确办理途径，
   **不要调用不相干的工具去凑**，也不要声称「已经帮你办好了」。
4. **选课/退课失败时**，把工具返回的确切原因告诉学生，不要自己重试，
   也不要在学生没要求时替换成别的课。
5. 你只能操作当前登录学生本人的数据，不能查询或修改他人的信息。

## 回答风格
用中文，简洁、具体、口语化。学生问什么就答什么，不要堆砌无关信息。
如果学生的问题缺少必要信息（比如没说课程代码），直接问清楚再动手。
"""


async def _build_mcp_client(ticket: str) -> Any:
    """为**本次请求**新建 MCP 客户端，票据放在请求头里。

    注意 transport 取值是 **下划线** 的 `streamable_http`，
    与服务端 `mcp.run(transport="streamable-http")`（连字符）不同。
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient(
        {
            "campus": {
                "transport": "streamable_http",
                "url": settings.mcp_server_url,
                "headers": {"Authorization": f"Bearer {ticket}"},
            }
        },
        # MCP 规范只保证工具名在单个 server 内唯一，聚合多服务必须加前缀。
        # 目前只有一个 server，但保持开启可以让后续加服务时不改代码。
        tool_name_prefix=True,
    )


async def build_agent(ticket: str) -> tuple[Any, dict[str, Any]]:
    """构建一次性的 Agent 实例，返回 (agent, 元信息)。"""
    client = await _build_mcp_client(ticket)
    tools = await client.get_tools()
    tool_names = [t.name for t in tools]

    interrupt_on = build_interrupt_on(tool_names)
    audit = audit_tool_names(tool_names)

    model = build_model()
    agent = create_agent(
        model,
        tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # 只登记写工具；读工具不登记 → 「查个课表也要审批」这种骚扰不会发生。
            # description_prefix 是中间件生成审批说明时的前缀，默认是英文的
            # "Tool execution requires approval"，全中文界面下必须覆盖掉。
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="此操作会修改你的数据，需要你确认",
            ),
            # 防止模型陷入「调工具 → 不满意 → 再调」的死循环
            ToolCallLimitMiddleware(tool_name=None, run_limit=8),
        ],
        checkpointer=_CHECKPOINTER,
    )

    # 工具详情的来源是 MCP 客户端，不是 agent ——
    # `create_agent` 返回的是编译后的图，上面没有 `.tools` 属性，
    # 想从 agent 反查工具列表会拿到空。
    tool_details = []
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        params: list[str] = []
        if schema is not None and hasattr(schema, "model_json_schema"):
            params = list(schema.model_json_schema().get("properties", {}).keys())
        tool_details.append(
            {
                "name": tool.name,
                "description_length": len(getattr(tool, "description", "") or ""),
                "parameters": params,
                # 身份字段不应该出现在任何工具的对外参数里（上线自检项）
                "has_identity_param": any(
                    p.lower()
                    in {"user_id", "student_no", "username", "user", "student_id"}
                    for p in params
                ),
                "is_write": is_write_tool(tool.name),
            }
        )

    meta = {
        "tools": tool_names,
        "tool_details": tool_details,
        "write_tools": sorted(interrupt_on.keys()),
        "audit": audit,
        "model": describe_provider(),
    }
    return agent, meta


# --------------------------------------------------------------------------- SSE


def sse(event: str, data: Any) -> str:
    """构造一个 SSE 帧。

    `ensure_ascii=False` 是必须的：默认 True 会把中文转成 \\uXXXX，
    前端要么显示成乱码，要么得额外反转义。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _tool_label(name: str) -> str:
    return {
        "list_courses": "查询课程列表",
        "get_course_detail": "查询课程详情",
        "get_my_schedule": "查询我的课表",
        "get_my_grades": "查询我的成绩",
        "search_knowledge": "检索学校规章制度",
        "enroll_course": "选课（需要你确认）",
        "drop_course": "退课（需要你确认）",
    }.get(name.split("_", 1)[-1] if name.startswith("campus_") else name, name)


def _short(text: str, limit: int = 400) -> str:
    text = content_to_text(text).strip()
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字）"


async def stream_chat(
    agent: Any,
    message: str,
    thread_id: str,
) -> AsyncIterator[str]:
    """跑一轮 Agent，把过程以 SSE 帧的形式吐出来。"""
    config = {"configurable": {"thread_id": thread_id}}
    payload = {"messages": [{"role": "user", "content": message}]}

    yield sse("start", {"thread_id": thread_id})
    yield sse("status", {"stage": "thinking", "label": "正在思考…"})

    steps = 0
    interrupted = False
    try:
        async for mode, chunk in agent.astream(
            payload, config, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                msg_chunk, meta = chunk
                node = (meta or {}).get("langgraph_node", "")
                # 只推最终回答的 token，不推工具调用内部的中间文本
                if node == "model":
                    # 必须归一化：流经图之后的 content 可能是内容块列表
                    text = content_to_text(getattr(msg_chunk, "content", ""))
                    if text:
                        yield sse("token", {"text": text})

            elif mode == "updates":
                for node, update in (chunk or {}).items():
                    # 中断载荷：LangGraph 在人机交互中断时以 __interrupt__ 作为 key
                    if node == "__interrupt__":
                        interrupted = True
                        for item in update if isinstance(update, (list, tuple)) else [update]:
                            value = getattr(item, "value", item)
                            actions = []
                            for req in (value or {}).get("action_requests", []):
                                actions.append(
                                    {
                                        "name": req.get("name", ""),
                                        "args": req.get("args", {}),
                                        "description": req.get("description", ""),
                                        "label": _tool_label(req.get("name", "")),
                                    }
                                )
                            yield sse(
                                "interrupt",
                                {"thread_id": thread_id, "actions": actions},
                            )
                        continue

                    messages = (update or {}).get("messages")
                    if not messages:
                        continue
                    if not isinstance(messages, list):
                        messages = [messages]

                    for msg in messages:
                        mtype = getattr(msg, "type", "")

                        # 模型请求调工具
                        if mtype == "ai" and getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                steps += 1
                                yield sse(
                                    "tool_call",
                                    {
                                        "id": tc.get("id", ""),
                                        "name": tc.get("name", ""),
                                        "args": tc.get("args", {}),
                                        "label": _tool_label(tc.get("name", "")),
                                    },
                                )
                            yield sse(
                                "status",
                                {"stage": "calling_tool", "label": "正在调用工具…"},
                            )

                        # 工具返回
                        elif mtype == "tool":
                            # ToolMessage.content 实测是内容块列表，不做归一化
                            # 前端会看到 [{'type': 'text', ...}] 这种 Python repr
                            content = content_to_text(getattr(msg, "content", ""))
                            name = getattr(msg, "name", "")
                            ok = not content.startswith(("操作失败", "选课未成功", "退课未成功"))
                            # 中间的 ToolMessage 只是给模型看的，前端不用展示全文
                            yield sse(
                                "tool_result",
                                {
                                    "id": getattr(msg, "tool_call_id", ""),
                                    "name": name,
                                    "label": _tool_label(name),
                                    "ok": ok,
                                    "content": _short(content, 600),
                                    "summary": _short(content.split("\n")[0], 90),
                                },
                            )

        if interrupted:
            yield sse("status", {"stage": "waiting_approval", "label": "等待你确认…"})
        else:
            yield sse("status", {"stage": "done", "label": "已完成"})
            yield sse("done", {"thread_id": thread_id, "steps": steps})

    except Exception as exc:  # noqa: BLE001 — 任何异常都要让前端能看到，而不是静默断开
        yield sse(
            "error",
            {"message": f"{type(exc).__name__}: {exc}", "thread_id": thread_id},
        )


async def stream_resume(
    agent: Any,
    decisions: list[dict],
    thread_id: str,
    action_names: list[str] | None = None,
) -> AsyncIterator[str]:
    """审批后恢复执行。

    `decisions` 形如 `[{"type": "approve"}]` 或 `[{"type": "reject", "message": "理由"}]`。
    拒绝时框架会自动生成一条带拒绝理由的 ToolMessage 回灌给模型，
    于是模型能向用户解释「因为你拒绝了，所以没有执行」—— 这本身就是审计记录。

    `action_names` 与 decisions 同序，用来把 ToolMessage 对应回具体决定。
    同一次中断里可能有多个同名工具（例如连选两门课），只按工具名匹配会串位。
    """
    config = {"configurable": {"thread_id": thread_id}}
    pending_decisions = deque(
        zip(action_names, decisions)
        if action_names and len(action_names) == len(decisions)
        else ((None, d) for d in decisions)
    )

    yield sse("status", {"stage": "resuming", "label": "正在按你的决定继续…"})

    steps = 0
    interrupted = False
    try:
        async for mode, chunk in agent.astream(
            Command(resume={"decisions": decisions}),
            config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                msg_chunk, meta = chunk
                node = (meta or {}).get("langgraph_node", "")
                if node == "model":
                    # 必须归一化：流经图之后的 content 可能是内容块列表
                    text = content_to_text(getattr(msg_chunk, "content", ""))
                    if text:
                        yield sse("token", {"text": text})

            elif mode == "updates":
                for node, update in (chunk or {}).items():
                    if node == "__interrupt__":
                        interrupted = True
                        for item in update if isinstance(update, (list, tuple)) else [update]:
                            value = getattr(item, "value", item)
                            actions = [
                                {
                                    "name": req.get("name", ""),
                                    "args": req.get("args", {}),
                                    "description": req.get("description", ""),
                                    "label": _tool_label(req.get("name", "")),
                                }
                                for req in (value or {}).get("action_requests", [])
                            ]
                            yield sse(
                                "interrupt", {"thread_id": thread_id, "actions": actions}
                            )
                        continue

                    messages = (update or {}).get("messages")
                    if not messages:
                        continue
                    if not isinstance(messages, list):
                        messages = [messages]
                    for msg in messages:
                        mtype = getattr(msg, "type", "")
                        if mtype == "ai" and getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                steps += 1
                                yield sse(
                                    "tool_call",
                                    {
                                        "id": tc.get("id", ""),
                                        "name": tc.get("name", ""),
                                        "args": tc.get("args", {}),
                                        "label": _tool_label(tc.get("name", "")),
                                    },
                                )
                        elif mtype == "tool":
                            # ToolMessage.content 实测是内容块列表，不做归一化
                            # 前端会看到 [{'type': 'text', ...}] 这种 Python repr
                            content = content_to_text(getattr(msg, "content", ""))
                            name = getattr(msg, "name", "")

                            decision_type = ""
                            if pending_decisions:
                                next_name, next_decision = pending_decisions[0]
                                if next_name is None or next_name == name:
                                    pending_decisions.popleft()
                                    decision_type = str(next_decision.get("type", ""))

                            rejected = decision_type == "reject"
                            ok = not rejected and not content.startswith(
                                ("操作失败", "选课未成功", "退课未成功")
                            )
                            yield sse(
                                "tool_result",
                                {
                                    "id": getattr(msg, "tool_call_id", ""),
                                    "name": name,
                                    "label": _tool_label(name),
                                    "ok": ok,
                                    "decision": decision_type,
                                    "content": _short(content, 600),
                                    "summary": _short(content.split("\n")[0], 90),
                                },
                            )

        if interrupted:
            yield sse("status", {"stage": "waiting_approval", "label": "还有操作待确认…"})
        else:
            yield sse("status", {"stage": "done", "label": "已完成"})
            yield sse("done", {"thread_id": thread_id, "steps": steps})
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})


def get_checkpointer() -> InMemorySaver:
    return _CHECKPOINTER


async def get_state(agent: Any, thread_id: str) -> dict:
    """查某个会话当前的状态，用于拦截待审批会话。

    必须走编译后图的 `aget_state()`：checkpointer 的 `aget()` 只返回
    checkpoint 字典，没有 tasks/next，据此判断中断会永远得到 False。
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await agent.aget_state(config)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return snapshot_info(snapshot)
