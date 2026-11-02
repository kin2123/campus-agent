"""会话 key 的用户命名空间。

单独放在这里而不是 runtime.py，是为了让这个纯函数可以被测试，
不必为了验证隔离逻辑去导入整个 LangChain 运行时。
"""
from __future__ import annotations

import uuid


def thread_key(user_id: int, raw: str | None = None) -> str:
    """把客户端 thread_id 收进当前用户命名空间。

    客户端可以传任意字符串；如果直接拿它当 checkpointer key，A 的 thread_id
    被 B 拿到后，B 就能续写 A 的会话。这里统一加 `u<id>:` 前缀。
    对已带当前用户前缀的值保持幂等 —— 前端会把服务端返回的完整 id 原样回传。
    """
    prefix = f"u{user_id}:"
    if raw and raw.strip():
        value = raw.strip()
        return value if value.startswith(prefix) else f"{prefix}{value}"
    return f"{prefix}thread-{uuid.uuid4().hex[:12]}"
