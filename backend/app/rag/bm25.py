"""轻量 BM25 检索。

为什么要它：本地哈希 embedding 只有词面匹配能力，且「学分」这类高频词
在向量空间里权重过高，导致「一学期最多能选多少学分」会把「创新学分」排到第一。
BM25 的 IDF 项会**自动压低高频词的权重、抬高稀有词的权重**（「最多」「上限」这类），
正好补上这个缺陷。

语料只有几十到几千个 chunk，纯 Python 实现完全够用，不引入额外依赖。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按字 + 二元组。

    加二元组是关键：单字「学」「分」在中文里区分度极低，
    「学分」「选课」这样的二元组才是真实的信息单位。
    """
    raw = _TOKEN_RE.findall(text.lower())
    tokens = list(raw)
    cjk = [t for t in raw if "\u4e00" <= t <= "\u9fff"]
    tokens.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    return tokens


@dataclass
class BM25Doc:
    doc_id: str
    tf: Counter
    length: int


class BM25Index:
    """Okapi BM25，k1/b 用文献常用默认值。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: dict[str, BM25Doc] = {}
        self.df: Counter = Counter()
        self.avgdl: float = 0.0
        self._scores_cache: dict[str, float] = {}

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        if not tokens:
            return
        tf = Counter(tokens)
        self.docs[doc_id] = BM25Doc(doc_id=doc_id, tf=tf, length=len(tokens))
        for term in tf:
            self.df[term] += 1

    def finalize(self) -> None:
        n = len(self.docs)
        self.avgdl = (
            sum(d.length for d in self.docs.values()) / n if n else 0.0
        )

    def score(self, query: str) -> dict[str, float]:
        """返回 {doc_id: bm25 原始分}。只算查询词命中的文档，避免全量遍历。"""
        if not self.docs:
            return {}
        n = len(self.docs)
        q_terms = set(tokenize(query))
        if not q_terms:
            return {}

        scores: dict[str, float] = {}
        for term in q_terms:
            df = self.df.get(term, 0)
            if df == 0:
                continue
            # 标准 BM25 IDF（加 1 平滑，避免负分）
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for doc in self.docs.values():
                f = doc.tf.get(term, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (
                    1 - self.b + self.b * (doc.length / (self.avgdl or 1))
                )
                scores[doc.doc_id] = scores.get(doc.doc_id, 0.0) + idf * (
                    f * (self.k1 + 1) / denom
                )
        return scores


def normalize(scores: dict[str, float]) -> dict[str, float]:
    """按查询内最大值归一化到 0~1，方便和向量相似度加权相加。

    **不要用 min-max**。min-max 会把候选集里的最高分强行拉到 1.0，
    哪怕它的原始分很低 —— 实测中「退课有什么限制」会因此把只命中一个
    通用词（「什么」）的无关文档顶到 BM25 满分、排到正确的「退课规则」前面。
    除以最大值则保留相对比例：真正的强命中仍然是 1.0，弱命中会衰减到 0.0x。
    """
    if not scores:
        return {}
    hi = max(scores.values())
    if hi <= 0:
        return {k: 0.0 for k in scores}
    return {k: v / hi for k, v in scores.items()}
