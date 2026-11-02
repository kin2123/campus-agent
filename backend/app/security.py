"""鉴权：JWT 签发与校验。

两种票据，共用同一套密钥，但用 `typ` 区分用途：

| 票据 | typ | 有效期 | 谁持有 |
|---|---|---|---|
| 登录票据 | `access` | 12 小时 | 浏览器 localStorage |
| MCP 短票据 | `mcp_ticket` | 5 分钟 | 后端为单次 Agent 会话签发，放在 MCP 请求头里 |

短票据是「身份带外透传」的关键：它不经过模型、不出现在任何工具参数里，
模型既看不见也改不了，所以 Agent 无法越权。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from .config import settings

# 直接用 bcrypt，不经 passlib。
# passlib 1.7.4 需要读取 bcrypt.__about__.__version__，该属性在 bcrypt 4.1+ 被移除，
# 会打出 "error reading bcrypt version" 告警甚至在未来版本直接报错。多一层封装反而更脆。
import bcrypt as _bcrypt

# bcrypt 只处理前 72 字节，超长密码必须先截断，否则新版会直接抛错
_BCRYPT_MAX_BYTES = 72


def _prepare(raw: str) -> bytes:
    return raw.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(raw: str) -> str:
    return _bcrypt.hashpw(_prepare(raw), _bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(_prepare(raw), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001 — 哈希格式不合法时按验证失败处理
        return False


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(user_id),
            "username": username,
            "role": role,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        }
    )


def create_mcp_ticket(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(user_id),
            "username": username,
            "role": role,
            "typ": "mcp_ticket",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=settings.mcp_ticket_seconds)).timestamp()),
        }
    )


def decode_token(token: str, expected_typ: str | None = None) -> dict[str, Any] | None:
    """解码并校验票据。失败一律返回 None，调用方负责转成 401。"""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    if expected_typ and payload.get("typ") != expected_typ:
        return None
    return payload
