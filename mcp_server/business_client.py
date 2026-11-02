"""业务接口客户端 —— MCP 侧唯一与业务系统交互的出口。

## 核心：身份带外透传

MCP 工具**不接收 user_id / student_no 这类身份参数**。身份只有一个来源：
HTTP 请求头里的短票据。链条如下：

```
Agent 调工具（不带任何身份信息）
  → MCP 从 ctx.request_context.request.headers 取出短票据
  → httpx 调业务接口，把短票据放进 Authorization 原样转发
  → 业务接口照常鉴权 → 越权在此被拒
```

为什么这样设计：如果身份走工具参数，模型就能看见、能改、能伪造
（「帮 20230102 选课」这种 prompt injection 直接生效）。
走 HTTP 头是**带外通道**，模型既看不到也改不了。

## MCP 侧不做授权判断

只有「没有票据 → 401」这一条。真正的授权（容量、时间冲突、先修课）全在业务服务，
避免规则在两处漂移。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ._config import settings

# 工具调用是短请求，超时给足但不要无限等
TIMEOUT = httpx.Timeout(20.0, connect=5.0)

# 业务接口把业务拒绝放在 detail 里；这里统一拆出来给模型看
class ToolError(Exception):
    """给模型看的可读错误。不抛给框架，而是转成字符串返回。"""

    def __init__(self, message: str, code: str = "ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def extract_ticket(ctx: Any) -> str | None:
    """从 MCP 请求头里取短票据。

    实测 mcp 1.30.0：`Context.get_http_headers()` **不存在**
    （那是 2.x 才加的），必须走 `ctx.request_context.request.headers`。
    这是照抄教程最容易踩的一个坑。
    """
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _format_detail(detail: Any) -> tuple[str, str]:
    """把业务接口的 detail 拆成 (code, message)。"""
    if isinstance(detail, dict):
        return str(detail.get("code", "ERROR")), str(detail.get("message", detail))
    if isinstance(detail, str):
        return "ERROR", detail
    return "ERROR", json.dumps(detail, ensure_ascii=False)


async def call_business(
    ctx: Any,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    write: bool = False,
) -> Any:
    """调用业务接口。身份从 ctx 的请求头透传，不经过模型。

    write=True 时会额外带上 `X-Source: AI`，
    让业务层的审计日志能区分「人点的」和「Agent 代办的」。
    """
    ticket = extract_ticket(ctx)
    if not ticket:
        raise ToolError(
            "没有拿到有效的登录票据，无法读取或修改任何数据。"
            "请确认你是通过校园助手的对话界面发起请求的。",
            code="NO_TICKET",
        )

    headers = {"Authorization": f"Bearer {ticket}"}
    if write:
        # 双重标记：X-Source 给业务层写审计用，X-MCP-Ticket 便于排查
        headers["X-Source"] = "AI"
        headers["X-MCP-Ticket"] = "1"

    url = f"{settings.business_base_url}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.request(
                method, url, headers=headers, json=json_body, params=params
            )
        except httpx.RequestError as exc:
            raise ToolError(
                f"无法连接业务服务（{url}）：{type(exc).__name__}。"
                "请确认后端服务已启动。",
                code="BACKEND_UNREACHABLE",
            ) from exc

    if resp.status_code == 401:
        raise ToolError(
            "登录票据已过期或无效，请重新登录后再试。", code="UNAUTHORIZED"
        )
    if resp.status_code == 403:
        raise ToolError("当前账号没有执行这个操作的权限。", code="FORBIDDEN")

    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        code, message = _format_detail(
            body.get("detail") if isinstance(body, dict) else body
        )
        raise ToolError(message, code=code)

    if resp.status_code == 204:
        return {}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text}
