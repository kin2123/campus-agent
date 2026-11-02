"""会话快照解析。

单独成模块是为了不依赖 LangChain，便于直接单测：
`checkpointer.aget()` 返回的是 checkpoint 字典，而判断中断必须看
编译后图 `aget_state()` 返回的 StateSnapshot。
"""
from __future__ import annotations

from typing import Any


def snapshot_info(snapshot: Any) -> dict[str, Any]:
    """把 StateSnapshot 归一化成路由层需要的字段。

    没有跑过的线程会得到一个空快照（created_at=None），
    不能用「snapshot is None」判断，否则会把「空会话」当成「存在」。
    """
    if snapshot is None:
        return {"exists": False}

    if getattr(snapshot, "created_at", None) is None:
        return {"exists": False}

    tasks = tuple(getattr(snapshot, "tasks", ()) or ())
    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    task_interrupts = tuple(
        interrupt
        for task in tasks
        for interrupt in (getattr(task, "interrupts", ()) or ())
    )
    return {
        "exists": True,
        "next": list(getattr(snapshot, "next", ()) or ()),
        "has_interrupt": bool(interrupts or task_interrupts),
    }
