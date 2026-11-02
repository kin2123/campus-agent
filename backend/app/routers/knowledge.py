"""知识库检索与来源接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import KnowledgeChunk, User
from ..rag import store
from ..schemas import KnowledgeHit, KnowledgeSearchResponse
from ..services import write_audit

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


@router.post("/search", response_model=KnowledgeSearchResponse, summary="知识库混合检索")
def search(
    q: str = Query(..., description="查询语句"),
    top_k: int = Query(4, ge=1, le=20),
    x_source: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeSearchResponse:
    hits = store.search(q, top_k=top_k)
    if x_source == "AI":
        write_audit(
            db,
            user=user,
            action="knowledge_search",
            target_type="knowledge",
            target_id=q[:40],
            detail={"top_k": top_k, "hits": [h.chunk_id for h in hits]},
            source="AI",
        )
    return KnowledgeSearchResponse(
        query=q,
        hits=[
            KnowledgeHit(
                chunk_id=h.chunk_id,
                source_file=h.source_file,
                title=h.title,
                content=h.content,
                score=h.score,
            )
            for h in hits
        ],
    )


@router.get("/sources", summary="知识库来源文件列表")
def sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.query(KnowledgeChunk.source_file).all()
    counts: dict[str, int] = {}
    for (source_file,) in rows:
        counts[source_file] = counts.get(source_file, 0) + 1
    return {
        "backend": store.backend_name(),
        "total_chunks": store.count(),
        "files": [{"file": name, "chunks": n} for name, n in sorted(counts.items())],
    }


@router.get("/chunks", summary="列出知识库分块（便于核对索引内容）")
def chunks(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows = db.query(KnowledgeChunk).limit(limit).all()
    return {
        "items": [
            {
                "chunk_id": r.chunk_id,
                "source_file": r.source_file,
                "title": r.title,
                "preview": r.content[:160],
            }
            for r in rows
        ]
    }
