"""FastAPI 业务后端入口。

职责（这个进程是「编排者」，不是单纯的 CRUD 服务）：
- 业务 REST：课程、选课、课表、成绩、审计
- RAG：知识库检索（Chroma + BM25 混合）
- Agent 编排：MCP 客户端、ReAct 循环、SSE 网关、人工审批

启动：
    python -m app.main
或由 scripts/run.ps1 统一拉起（端口 18000）。
"""
from __future__ import annotations

import sys

# 允许 `python app/main.py` 直接运行（此时 __package__ 为空）
if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import init_db
from .rag import store
from .routers import agent, audit, auth, courses, enrollments, knowledge
from .seed import seed, seed_current_semester, seed_history
from .services import sync_enrollment_counts

app = FastAPI(
    title="校园课程智能助手 API",
    description=(
        "AI Agent + RAG + MCP 全栈示例。\n\n"
        "- 业务 REST 在 `/api/*`\n"
        "- Agent 对话在 `/api/agent/chat`（SSE 流式）\n"
        "- MCP 工具服务是独立进程（默认 18001）\n"
    ),
    version="1.0.0",
)

# 前端跑在 5173，端口不同即跨域。开发环境放开。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # SSE 需要前端能读到这几个头
    expose_headers=["Content-Type", "Cache-Control"],
)

app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(enrollments.router)
app.include_router(knowledge.router)
app.include_router(audit.router)
app.include_router(agent.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = _get_session()
    try:
        created = seed(db)
        history = seed_history(db)
        current = seed_current_semester(db)
        # seed 直接写 enrollments，不经过 enroll_course，启动后校准一次座位计数。
        sync_enrollment_counts(db)
    finally:
        db.close()

    print("=" * 70)
    print("  校园课程智能助手 · 业务后端")
    print(f"  http://{settings.host}:{settings.backend_port}")
    print(f"  接口文档 http://{settings.host}:{settings.backend_port}/docs")
    print(f"  模型：{settings.llm_provider}")
    print(f"  知识库向量后端：{store.backend_name()}")
    if created["courses"] or created["users"]:
        print(f"  初始化种子数据：新增课程 {created['courses']} 门、用户 {created['users']} 个")
    if history.get("history"):
        print(f"  补充历史成绩：{history['history']} 条")
    if current.get("current"):
        print(f"  补充本学期在选课程：{current['current']} 门")
    print("=" * 70)


def _get_session():
    from .db import SessionLocal

    return SessionLocal()


@app.get("/", summary="服务信息")
def root() -> dict:
    return {
        "service": "校园课程智能助手",
        "backend": f"http://{settings.host}:{settings.backend_port}",
        "mcp_server": settings.mcp_server_url,
        "docs": "/docs",
        "model_provider": settings.llm_provider,
        "rag_backend": store.backend_name(),
    }


@app.get("/health", summary="健康检查")
def health() -> dict:
    return {
        "status": "ok",
        "mcp_url": settings.mcp_server_url,
        "llm_provider": settings.llm_provider,
        "rag_backend": store.backend_name(),
        "knowledge_chunks": store.count(),
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
    """未捕获异常也返回结构化 JSON，方便前端展示而不是看到一坨 HTML。"""
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.backend_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
