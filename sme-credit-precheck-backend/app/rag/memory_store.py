"""进程内 dict 实现的 VectorStore。

优点：零依赖、秒级启动、pytest 里直接 new 就能用。
缺点：进程重启丢失数据、向量多了 query 会慢（O(N) 全量 cosine）。
适合：开发 / 测试 / 数据量 < 1 万条的小知识库。
"""

from __future__ import annotations

import logging
import math
import uuid
from collections import defaultdict

from app.rag.base import Document, QueryResult, VectorStore

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """cosine 相似度。两向量长度不同时返回 0（视为不相似）。"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _match_where(meta: dict, where: dict | None) -> bool:
    """简单等值匹配：where 里所有 key 都在 meta 里且值相等 → True。"""
    if not where:
        return True
    return all(meta.get(k) == v for k, v in where.items())


class InMemoryStore(VectorStore):
    """进程内 dict 存向量。collection→{doc_id: Document}。"""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Document]] = defaultdict(dict)

    # ---- VectorStore 实现 ----

    def upsert(self, documents: list[Document], collection: str | None = None) -> None:
        col = collection or "__default__"
        bucket = self._store[col]
        for doc in documents:
            if not doc.id:
                doc.id = uuid.uuid4().hex
            bucket[doc.id] = doc

    def query(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        where: dict | None = None,
        collection: str | None = None,
    ) -> list[QueryResult]:
        col = collection or "__default__"
        bucket = self._store.get(col, {})
        scored: list[tuple[float, Document]] = []
        for doc in bucket.values():
            if not _match_where(doc.metadata, where):
                continue
            scored.append((_cosine(vector, doc.vector), doc))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [QueryResult(document=d, score=s) for s, d in scored[:top_k]]

    def delete(self, ids: list[str], collection: str | None = None) -> None:
        col = collection or "__default__"
        bucket = self._store.get(col)
        if bucket is None:
            return
        for _id in ids:
            bucket.pop(_id, None)

    def list_collections(self) -> list[str]:
        return sorted(self._store.keys())

    # ---- 可选能力 ----

    def reset_collection(self, collection: str | None = None) -> None:
        if collection is None:
            self._store.clear()
        else:
            self._store.pop(collection, None)

    def get_collection_stats(self, collection: str | None = None) -> dict:
        if collection is None:
            return {name: len(bucket) for name, bucket in self._store.items()}
        bucket = self._store.get(collection, {})
        return {"count": len(bucket)}
