"""RAG 检索质量评测。

用带标注的查询集量化 Hit@1 / Hit@3 / Hit@4，而不是靠肉眼看几条结果就说"效果还行"。

判定方式：正确答案用**必备关键词**表示（如「30 学分」「15%」），
只要该关键词出现在 Top-k 召回的原文里就算命中。

这样标注的好处是：不依赖 chunk_id 这种会随分块策略变化的内部标识，
改分块参数后评测集不用重写。

用法：
    python scripts/eval_rag.py
    python scripts/eval_rag.py --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.rag import store  # noqa: E402

# (查询, [必备关键词...])  —— 关键词必须能在召回的 chunk 原文里找到
CASES: list[tuple[str, list[str]]] = [
    ("一学期最多能选多少学分", ["不超过 30 学分"]),
    ("退课有什么限制", ["已出成绩的课程不能退课"]),
    ("毕业设计查重率要求多少", ["15%"]),
    ("挂科了还能申请奖学金吗", ["无不及格课程"]),
    ("缓考怎么申请", ["缓考申请表"]),
    ("转专业需要什么条件", ["前 30%"]),
    ("专业选修课要选几个方向", ["3 个方向"]),
    ("生产实习要交什么材料", ["实习单位鉴定意见"]),
    ("校园网每月多少流量", ["30 GB"]),
    ("考试作弊会怎么处理", ["开除学籍"]),
    ("毕业需要多少学分", ["165 学分"]),
    ("补考成绩单上显示多少分", ["60 分"]),
    ("国家奖学金多少钱", ["8000 元"]),
    ("实验室设备能借多久", ["7 天"]),
    ("入党需要多长时间", ["预备期 1 年"]),
    ("助学贷款最高能贷多少", ["16000 元"]),
    ("成绩单打印收费吗", ["前 3 份免费"]),
    ("保研需要六级吗", ["CET-6 425 分"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="打印每条查询的召回详情")
    args = parser.parse_args()

    print(f"向量库后端：{store.backend_name()}")
    print(f"语料 chunk 数：{store.count()}")
    print(f"评测集：{len(CASES)} 条查询")
    print("=" * 78)

    hits1 = hits3 = hits4 = 0
    failures: list[tuple[str, list[str], list[str]]] = []

    for query, keywords in CASES:
        results = store.search(query, top_k=4)
        top4_text = "\n".join(h.content for h in results)
        top1_text = results[0].content if results else ""

        ok1 = any(kw in top1_text for kw in keywords)
        ok3 = any(kw in "\n".join(h.content for h in results[:3]) for kw in keywords)
        ok4 = any(kw in top4_text for kw in keywords)

        hits1 += ok1
        hits3 += ok3
        hits4 += ok4

        mark = "OK  " if ok1 else ("T3  " if ok3 else ("T4  " if ok4 else "MISS"))
        print(f"[{mark}] {query}")
        if args.verbose or not ok4:
            for i, h in enumerate(results, 1):
                flag = ""
                if any(kw in h.content for kw in keywords):
                    flag = "  <<< 含答案"
                print(f"        {i}. [rrf {h.score:.5f}] {h.title[:44]}{flag}")
        if not ok4:
            failures.append((query, keywords, [h.title for h in results]))

    n = len(CASES)
    print("=" * 78)
    print(f"Hit@1 : {hits1}/{n} = {hits1 / n:.1%}")
    print(f"Hit@3 : {hits3}/{n} = {hits3 / n:.1%}")
    print(f"Hit@4 : {hits4}/{n} = {hits4 / n:.1%}")
    if failures:
        print("\n未命中（Hit@4 也找不到）：")
        for query, keywords, titles in failures:
            print(f"  - {query}  期望关键词 {keywords}")
            for t in titles:
                print(f"      召回: {t[:56]}")
    return 0 if hits4 == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
