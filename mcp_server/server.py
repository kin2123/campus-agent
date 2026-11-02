"""FastMCP 工具服务入口。

启动：
    python -m mcp_server.server
或由 scripts/run.ps1 统一拉起（端口 18001）。

## 为什么 transport 用 streamable-http

它的请求/响应是标准 HTTP，可以在**每个请求的头里带上短票据**，
从而支持「不同用户各自的身份」——这是 stdio 传输做不到的
（stdio 是单进程长连接，没法按请求切身份）。
Agent 侧要在多用户环境下复用同一个 MCP 服务，就必须用 HTTP 传输。

## 两个必须记住的写法差异

| 位置 | 取值 | 连字符/下划线 |
|---|---|---|
| 服务端 `mcp.run(transport=...)` | `"streamable-http"` | **连字符** |
| 客户端连接配置 `{"transport": ...}` | `"streamable_http"` | **下划线** |

写反了不会报参数错误，而是连接不上或静默失败，很难排查。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ._config import settings
from .tools import ALL_TOOLS

mcp = FastMCP(
    name="campus-course-tools",
    instructions=(
        "校园课程智能助手的业务工具集。提供课程查询、课表与成绩查询、"
        "制度知识库检索，以及选课/退课两个需要人工确认的写操作。\n\n"
        "身份由请求头中的登录票据自动携带，工具参数里不需要也不接受任何用户标识 —— "
        "所有工具都只作用于当前登录学生本人。"
    ),
    host=settings.host,
    port=settings.mcp_port,
    # streamable-http 的默认路径，与 Agent 侧连接配置的 url 必须一致
    streamable_http_path="/mcp",
    # 无状态模式：每次请求独立，不要求先 initialize 建会话。
    # 这让「每个 HTTP 请求带自己的票据」这件事变得自然，
    # 也避免了会话串号（用户 A 的会话被用户 B 复用）。
    stateless_http=True,
    json_response=True,
)

for _tool in ALL_TOOLS:
    # 逐个显式注册，而不是批量 add_tool，便于启动日志核对工具清单
    mcp.add_tool(_tool)


def main() -> None:
    print("=" * 70)
    print("  MCP 工具服务（校园课程）")
    print(f"  监听：http://{settings.host}:{settings.mcp_port}/mcp")
    print(f"  传输：streamable-http（stateless）")
    print(f"  回调业务接口：{settings.business_base_url}")
    print(f"  工具数：{len(ALL_TOOLS)}")
    for tool in ALL_TOOLS:
        kind = "写(需审批)" if tool.__name__.startswith(("enroll", "drop")) else "读"
        print(f"    - {tool.__name__:20s} [{kind}]")
    print("=" * 70)
    mcp.run(transport="streamable-http")  # 注意：连字符


if __name__ == "__main__":
    main()
