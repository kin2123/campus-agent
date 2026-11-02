"""API 探测脚本 —— 动手写业务代码前先跑这个。

MCP / LangChain 生态迭代极快，教程里的 import 路径、参数名、transport 取值
经常已经失效。与其照抄后调试半天，不如 5 分钟把真实签名打出来。

用法：
    python scripts/probe_apis.py
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

OK, FAIL = "[OK]  ", "[FAIL]"


def probe(label: str, dotted: str):
    try:
        mod = importlib.import_module(dotted)
        print(f"{OK} {label} -> {dotted}")
        return mod
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {label} -> {dotted}: {type(exc).__name__}: {exc}")
        return None


def sig(obj, label: str) -> None:
    try:
        print(f"      {label}{inspect.signature(obj)}")
    except (TypeError, ValueError) as exc:
        print(f"      {label}<无法获取签名: {exc}>")


print("=" * 78)
print("版本清单")
print("=" * 78)
for pkg in (
    "mcp", "langchain", "langchain-core", "langgraph",
    "langchain-mcp-adapters", "chromadb", "fastapi", "sqlalchemy",
):
    try:
        print(f"  {pkg:28s} {md.version(pkg)}")
    except md.PackageNotFoundError:
        print(f"  {pkg:28s} <未安装>")

print()
print("=" * 78)
print("1. FastMCP 服务端（坑 1：1.x 与 2.x 模块名不同）")
print("=" * 78)
fastmcp_mod = probe("mcp.server.fastmcp", "mcp.server.fastmcp")
if fastmcp_mod is None:
    fastmcp_mod = probe("mcp.server.mcpserver（2.x 新名）", "mcp.server.mcpserver")
if fastmcp_mod:
    FastMCP = getattr(fastmcp_mod, "FastMCP", None)
    if FastMCP:
        sig(FastMCP.__init__, "FastMCP(*args) ")
        run = FastMCP.run if hasattr(FastMCP, "run") else None
        if run:
            sig(run, "FastMCP.run ")
        # transport 合法取值
        try:
            src = inspect.getsource(FastMCP.run)
            for line in src.splitlines():
                if "transport" in line and ("Literal" in line or "==" in line):
                    print(f"      transport 提示: {line.strip()[:110]}")
        except Exception as exc:  # noqa: BLE001
            print(f"      无法读 FastMCP.run 源码: {exc}")
    print(f"      FastMCP 公开成员: "
          f"{[n for n in dir(fastmcp_mod) if not n.startswith('_')][:12]}")

print()
print("=" * 78)
print("2. MCP Context —— 读 HTTP 头（坑 3：用户说 get_http_headers 不存在）")
print("=" * 78)
ctx_mod = probe("mcp.server.fastmcp.Context", "mcp.server.fastmcp.server")
try:
    from mcp.server.fastmcp import Context  # type: ignore

    print(f"{OK} Context 导入成功")
    print(f"      Context 有 get_http_headers 吗: "
          f"{hasattr(Context, 'get_http_headers')}")
    print(f"      Context 公开成员: "
          f"{[n for n in dir(Context) if not n.startswith('_')]}")
    sig(Context.request_context.fget, "request_context（property）")  # type: ignore[attr-defined]
except Exception as exc:  # noqa: BLE001
    print(f"{FAIL} Context: {type(exc).__name__}: {exc}")
print(f"      request_context 类型: "
      f"{'RequestContext' if hasattr(ctx_mod, 'RequestContext') else '见 mcp.shared.context'}")

print()
print("=" * 78)
print("3. LangChain Agent（坑 4：create_react_agent 已移除）")
print("=" * 78)
agents_mod = probe("langchain.agents", "langchain.agents")
if agents_mod:
    names = [n for n in dir(agents_mod) if not n.startswith("_")]
    print(f"      langchain.agents 公开成员: {names}")
    print(f"      有 create_agent 吗: {hasattr(agents_mod, 'create_agent')}")
    print(f"      有 create_react_agent 吗（应已移除）: "
          f"{hasattr(agents_mod, 'create_react_agent')}")
    if hasattr(agents_mod, "create_agent"):
        sig(agents_mod.create_agent, "create_agent")

print()
print("=" * 78)
print("4. HITL 中间件与 checkpointer")
print("=" * 78)
mw_mod = probe("langchain.agents.middleware", "langchain.agents.middleware")
if mw_mod:
    print(f"      公开成员: {[n for n in dir(mw_mod) if not n.startswith('_')]}")
    HITL = getattr(mw_mod, "HumanInTheLoopMiddleware", None)
    if HITL:
        sig(HITL.__init__, "HumanInTheLoopMiddleware ")
        doc = (HITL.__doc__ or "").strip().splitlines()
        for line in doc[:12]:
            print(f"      | {line.strip()}")
cp_mod = probe("langgraph.checkpoint.memory", "langgraph.checkpoint.memory")
if cp_mod:
    print(f"      公开成员: {[n for n in dir(cp_mod) if not n.startswith('_')]}")
types_mod = probe("langgraph.types (Command)", "langgraph.types")
if types_mod:
    print(f"      公开成员: {[n for n in dir(types_mod) if not n.startswith('_')]}")

print()
print("=" * 78)
print("5. MCP 客户端适配器（坑 2/10：transport 下划线、tool_name_prefix）")
print("=" * 78)
mcp_adapters = probe("langchain_mcp_adapters.client", "langchain_mcp_adapters.client")
if mcp_adapters:
    MSC = getattr(mcp_adapters, "MultiServerMCPClient", None)
    if MSC:
        sig(MSC.__init__, "MultiServerMCPClient ")
        print("      MCP client 连接配置支持的字段：")
        try:
            from langchain_mcp_adapters.sessions import (  # type: ignore
                SSEConnection,
                StdioConnection,
                StreamableHttpConnection,
            )

            for name, conn in (
                ("StreamableHttpConnection", StreamableHttpConnection),
                ("SSEConnection", SSEConnection),
                ("StdioConnection", StdioConnection),
            ):
                hints = getattr(conn, "__annotations__", {})
                keys = [k for k in hints if k != "session_kwargs"]
                print(f"        {name}: {keys}")
        except Exception as exc:  # noqa: BLE001
            print(f"        无法导入 sessions 类型: {type(exc).__name__}: {exc}")

print()
print("=" * 78)
print("6. Chroma（自定义 embedding_function 的接口约定）")
print("=" * 78)
try:
    import chromadb

    print(f"{OK} chromadb {md.version('chromadb')}")
    sig(chromadb.PersistentClient.__init__, "PersistentClient ")
    client = chromadb.PersistentClient(path=str(ROOT / "data" / "_probe_chroma"))
    print(f"{OK} PersistentClient 实例化成功")
    print(f"      client 公开方法: {[n for n in dir(client) if not n.startswith('_')]}")

    class ProbeEF:
        def __call__(self, input):  # noqa: A002
            return [[0.1] * 8 for _ in input]

        def name(self):
            return "probe-ef"

    col = client.get_or_create_collection(
        name="_probe_collection", embedding_function=ProbeEF()
    )
    col.upsert(ids=["a"], documents=["测试文档"], metadatas=[{"k": "v"}])
    res = col.query(query_texts=["测试"], n_results=1,
                    include=["documents", "metadatas", "distances"])
    print(f"{OK} upsert + query 成功，返回键: {list(res.keys())}")
    print(f"      命中: ids={res['ids']} distances={res.get('distances')}")
    sig(col.query, "collection.query ")
except Exception as exc:  # noqa: BLE001
    import traceback

    print(f"{FAIL} Chroma: {type(exc).__name__}: {exc}")
    traceback.print_exc(limit=3)

print()
print("=" * 78)
print("7. 自定义假模型所需的基类（坑 12：PrivateAttr vs Field）")
print("=" * 78)
lc_core = probe("langchain_core.language_models.chat_models", 
                "langchain_core.language_models.chat_models")
for dotted in (
    "langchain_core.messages",
    "langchain_core.outputs",
    "langchain_core.tools",
):
    probe(dotted, dotted)
try:
    from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: F401

    print(f"{OK} ChatResult / ChatGeneration 可导入")
except Exception as exc:  # noqa: BLE001
    print(f"{FAIL} ChatResult/ChatGeneration: {exc}")
try:
    from pydantic import PrivateAttr  # noqa: F401

    print(f"{OK} pydantic.PrivateAttr 可用")
except Exception as exc:  # noqa: BLE001
    print(f"{FAIL} PrivateAttr: {exc}")

print()
print("=" * 78)
print("探测完成。请按上面的**实际**结果写业务代码，不要照抄教程。")
print("=" * 78)
