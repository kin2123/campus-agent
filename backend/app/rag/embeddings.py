"""Embedding 后端，可插拔。

| backend | 说明 |
|---|---|
| `local` | 内置字符 n-gram 哈希向量，零 Key、零网络、开箱可用 |
| `openai_compatible` | 调任意 OpenAI 兼容的 /embeddings 端点（智谱、通义、DeepSeek、OpenAI 均可） |

诚实说明 `local` 的能力边界：它本质是**词面匹配的向量化**，能抓住「学分上限」「退课」
这类术语重合，但抓不住「我不想上了怎么退」和「退课流程」之间的语义等价。
所以检索层额外做了一层关键词重排来补偿（见 store.py），
接上真实 embedding 后重排权重会自动降低。
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Any

import httpx

from ..config import settings

LOCAL_DIM = 512

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    """中英混合分词：英文按词，中文按字 + 二元组。

    中文单字信息量太低（「学」「分」到处都是），加二元组能显著提升区分度。
    """
    raw = _TOKEN_RE.findall(text.lower())
    tokens = list(raw)
    # 中文二元组
    cjk = [t for t in raw if "\u4e00" <= t <= "\u9fff"]
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return tokens


def _hash_index(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % LOCAL_DIM


def _local_embed(text: str) -> list[float]:
    vec = [0.0] * LOCAL_DIM
    for token in _tokens(text):
        vec[_hash_index(token)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _remote_embed(texts: list[str]) -> list[list[float]]:
    base = settings.llm_base_url.rstrip("/")
    url = f"{base}/embeddings"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": settings.embedding_model, "input": texts},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


class EmbeddingFunction:
    """Chroma 自定义向量函数。

    实测 chromadb 1.5.9 的调用约定（读源码 api/models/CollectionCommon.py:745 `_embed` 得到）：

    | 场景 | 调用的方法 | 传入的 input |
    |---|---|---|
    | upsert / add | `__call__` | `list[str]` |
    | query | `embed_query` | `list[str]` |

    两个坑：
    1. **必须显式实现 `embed_query`**。`EmbeddingFunction` 协议里 `embed_query` 有默认实现
       （转调 `__call__`），但那个默认只在**继承该 Protocol** 时生效；纯自定义类会直接
       `AttributeError: 'X' object has no attribute 'embed_query'`。
    2. `embed_query` 收到的是**列表**，不是单个字符串。按单字符串写会在 query 时崩。
    """

    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or settings.embedding_backend
        self.dim = LOCAL_DIM if self.backend == "local" else 0

    @staticmethod
    def _as_list(texts: Any) -> list[str]:
        if isinstance(texts, str):
            return [texts]
        return [str(t) for t in texts]

    def _embed(self, texts: Any) -> list[list[float]]:
        items = self._as_list(texts)
        if self.backend == "local":
            return [_local_embed(t) for t in items]
        return _remote_embed(items)

    def __call__(self, input: Any) -> list[list[float]]:  # noqa: A002 — chroma 固定形参名
        return self._embed(input)

    def embed_query(self, input: Any) -> list[list[float]]:  # noqa: A002
        return self._embed(input)

    # chroma 可能调用这几个做 collection 元数据持久化
    def name(self) -> str:
        return f"campus-{self.backend}"

    def build_from_config(self, config: dict) -> "EmbeddingFunction":
        return EmbeddingFunction(backend=(config or {}).get("backend", self.backend))

    def get_config(self) -> dict:
        return {"backend": self.backend}

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]

    def embed_query_one(self, text: str) -> list[float]:
        """内部检索用：拿单个查询的向量。"""
        return self._embed([text])[0]


@lru_cache
def get_embedding_function() -> EmbeddingFunction:
    return EmbeddingFunction()


def local_embed(text: str) -> list[float]:
    """暴露给检索重排用的纯本地向量。"""
    return _local_embed(text)


def keyword_overlap(query: str, text: str) -> float:
    """Jaccard 式关键词重合度，取值 0~1。用来补偿哈希向量的语义缺陷。"""
    q = set(_tokens(query))
    t = set(_tokens(text))
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)
