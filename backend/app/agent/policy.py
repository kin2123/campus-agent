"""Agent 的写操作策略：哪些工具需要人工审批。

## 为什么需要这一层

如果只有一份写工具清单放在 MCP 服务里，Agent 侧就得同步维护一份，
迟早出现「新加了写工具但忘了登记审批」—— 那是安全事故，不是 bug。

这里的做法是**双保险**：
1. 显式清单 `WRITE_TOOL_NAMES`（审批的判定依据）
2. `audit_tool_names()` 把 MCP 实际暴露的工具和清单做比对，
   发现清单外但名字带写动词的工具就报出来（见 /api/agent/tools 接口）
"""
from __future__ import annotations

# 需要人工审批的写工具（按「去掉服务前缀后的名字」匹配）
WRITE_TOOL_NAMES: set[str] = {
    "enroll_course",
    "drop_course",
}

# 名字里出现这些动词、又不在上面清单里的工具，会被标记为「疑似写工具」并告警
WRITE_VERB_HINTS: tuple[str, ...] = (
    "enroll", "drop", "create", "update", "delete", "cancel",
    "submit", "modify", "change", "reset", "approve", "pay", "set_",
)


def strip_prefix(tool_name: str) -> str:
    """去掉 MultiServerMCPClient 的 server 名前缀。

    `tool_name_prefix=True` 时工具名会变成 `<server>_<tool>`，
    因为 MCP 规范只保证工具名在**单个 server 内**唯一，
    聚合多个 server 必须加前缀。所以判定写工具前要先剥掉前缀。
    """
    if tool_name in WRITE_TOOL_NAMES:
        return tool_name
    for name in WRITE_TOOL_NAMES:
        if tool_name.endswith(f"_{name}"):
            return name
    return tool_name


def is_write_tool(tool_name: str) -> bool:
    return strip_prefix(tool_name) in WRITE_TOOL_NAMES


def build_interrupt_on(tool_names: list[str]) -> dict[str, bool]:
    """只登记写工具。

    读工具不登记 → 误拦率为 0（不会出现「查个课表还要审批」这种骚扰）。
    """
    return {name: True for name in tool_names if is_write_tool(name)}


def audit_tool_names(tool_names: list[str]) -> dict:
    """比对 MCP 暴露的工具与审批清单，返回审计结果。"""
    writes = [n for n in tool_names if is_write_tool(n)]
    suspicious = [
        n
        for n in tool_names
        if not is_write_tool(n)
        and any(h in strip_prefix(n).lower() for h in WRITE_VERB_HINTS)
    ]
    return {
        "total": len(tool_names),
        "write_tools": writes,
        "read_tools": [n for n in tool_names if n not in writes],
        "suspicious": suspicious,
        "ok": not suspicious,
        "hint": (
            "所有疑似写工具都已在审批清单中。"
            if not suspicious
            else f"注意：{suspicious} 看起来是写工具但不在审批清单里，"
                 "请把它们加入 app/agent/policy.py 的 WRITE_TOOL_NAMES。"
        ),
    }
