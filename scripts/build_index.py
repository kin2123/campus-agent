"""构建 / 重建知识库索引。

用法：
    python scripts/build_index.py            # 增量（同名 chunk 覆盖）
    python scripts/build_index.py --rebuild  # 清空重建

同时把分块原文镜像进 SQLite 的 knowledge_chunks 表，
一是便于前端列出知识库来源，二是评测 RAG 召回时能做基线核对。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import KnowledgeChunk  # noqa: E402
from app.rag import store  # noqa: E402
from app.rag.loader import load_all_chunks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="清空后重建")
    args = parser.parse_args()

    init_db()

    chunks = load_all_chunks()
    if not chunks:
        print("没有找到任何知识库文档，请检查 backend/kb/*.md")
        return 1

    print(f"分块完成：{len(chunks)} 个 chunk")
    by_file: dict[str, int] = {}
    for c in chunks:
        by_file[c.source_file] = by_file.get(c.source_file, 0) + 1
    for name, n in sorted(by_file.items()):
        print(f"  {name:38s} {n:3d} 块")

    print(f"\n向量库后端：{store.backend_name()}")
    written = store.index_chunks(chunks, rebuild=args.rebuild)
    print(f"写入向量库：{written} 个 chunk，当前总数 {store.count()}")

    # 镜像到 SQLite
    db = SessionLocal()
    try:
        if args.rebuild:
            db.query(KnowledgeChunk).delete()
            db.commit()
        existing = {row[0] for row in db.query(KnowledgeChunk.chunk_id).all()}
        added = 0
        for c in chunks:
            if c.chunk_id in existing:
                continue
            db.add(
                KnowledgeChunk(
                    chunk_id=c.chunk_id,
                    source_file=c.source_file,
                    title=c.title,
                    content=c.content,
                )
            )
            added += 1
        db.commit()
        total = db.query(KnowledgeChunk).count()
        print(f"镜像到 SQLite：新增 {added} 条，共 {total} 条")
    finally:
        db.close()

    print("\n--- 冒烟测试：RRF 混合检索 Top-3（vr=向量排名 br=BM25排名，0 表示该路未召回）---")
    for query in (
        "一学期最多能选多少学分",
        "退课有什么限制",
        "毕业设计查重率要求",
        "挂科了还能申请奖学金吗",
    ):
        print(f"\nQ: {query}")
        hits = store.search(query, top_k=3)
        if not hits:
            print("   （无召回）")
        for i, h in enumerate(hits, 1):
            snippet = h.content.replace("\n", " ")[:60]
            print(f"   {i}. [rrf {h.score:.5f} | vr {h.vec_rank:>2} br {h.bm25_rank:>2}] {h.title[:38]}")
            print(f"      {snippet}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
