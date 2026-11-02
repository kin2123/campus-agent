"""审批台账：interrupt 入账 + resume 结果回填。

这里不依赖 LangChain，方便直接用 SQLite 做单元测试。
路由层只负责把 SSE 帧交给它，不关心台账字段。
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone

from ..db import SessionLocal
from ..models import PendingAction


def parse_sse_frame(frame: str) -> tuple[str, dict] | None:
    """解析本服务自己产出的 SSE 帧（event + 单行 JSON data）。"""
    event = "message"
    data_line = ""
    for line in frame.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_line = line[5:].strip()
    if not data_line:
        return None
    try:
        return event, json.loads(data_line)
    except json.JSONDecodeError:
        return None


def record_pending_actions(thread_id: str, user_id: int, frame: str) -> None:
    """把 interrupt 里的待执行操作写入台账。

    即使最终被拒绝，这条记录也会保留（状态改为 rejected）——
    这是「Agent 尝试过什么」的完整证据链。
    """
    parsed = parse_sse_frame(frame)
    if parsed is None:
        return
    _event, data = parsed

    db = SessionLocal()
    try:
        for action in data.get("actions", []):
            db.add(
                PendingAction(
                    thread_id=thread_id,
                    user_id=user_id,
                    tool_name=action.get("name", ""),
                    args=json.dumps(action.get("args", {}), ensure_ascii=False),
                    description=action.get("description", "") or action.get("label", ""),
                    status="pending",
                )
            )
        db.commit()
    except Exception:  # noqa: BLE001 — 台账写失败不能影响主流程
        db.rollback()
    finally:
        db.close()


class ResumeLedger:
    """把 resume 流里的 tool_result 落到审批台账。

    批准不是最终结果：只有真正收到工具返回，才能确定这次写操作
    是成功、被业务拒绝，还是根本没执行。
    """

    def __init__(self, thread_id: str, user_id: int) -> None:
        self.thread_id = thread_id
        self.user_id = user_id
        # tool_name -> 本次批准且尚未拿到结果的台账行 id（按 interrupt 顺序）
        self.queues: dict[str, deque[int]] = {}
        self.results: dict[int, tuple[str, str | None]] = {}
        self.error: str | None = None

    def track_approved(self, rows: list[tuple[int, str]]) -> None:
        for row_id, tool_name in rows:
            self.queues.setdefault(tool_name, deque()).append(row_id)

    def on_event(self, frame: str) -> None:
        parsed = parse_sse_frame(frame)
        if parsed is None:
            return
        event, data = parsed
        if event == "tool_result":
            # 被拒绝的操作也会产生一条 ToolMessage（框架回灌给模型用），
            # 它不是批准行的执行结果，不能占掉队列里的位置。
            if data.get("decision") == "reject":
                return
            name = str(data.get("name", ""))
            queue = self.queues.get(name)
            if not queue:
                return
            row_id = queue.popleft()
            if data.get("ok") is False:
                content = str(data.get("content", ""))[:500] or "工具执行失败"
                self.results[row_id] = ("FAILED", content)
            else:
                self.results[row_id] = ("SUCCESS", None)
        elif event == "error":
            self.error = str(data.get("message", ""))[:500] or "执行出错"

    def flush(self) -> None:
        """把结果写回台账。客户端中途断开时也会在 finally 里调用。"""
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            for row_id, (result, error) in self.results.items():
                row = db.get(PendingAction, row_id)
                if row is None:
                    continue
                row.result = result
                row.error = error
                row.executed_at = now

            # 已批准但没等到工具返回：有错误算 FAILED，否则算没执行。
            fallback = "FAILED" if self.error else "NOT_EXECUTED"
            fallback_error = self.error or "执行流结束前未收到该工具的结果"
            for queue in self.queues.values():
                for row_id in queue:
                    row = db.get(PendingAction, row_id)
                    if row is None:
                        continue
                    row.result = fallback
                    row.error = fallback_error
                    row.executed_at = now
            db.commit()
        except Exception:  # noqa: BLE001 — 台账写失败不能影响流式响应
            db.rollback()
        finally:
            db.close()
