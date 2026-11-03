"""ChromaDB 持久化实现（占位）。

pip install chromadb 后可用。persist 到 data/chroma/ 目录，进程重启不丢数据。

和 InMemoryStore 的区别：
- 磁盘持久化，适合生产环境
- 内置向量索引（HNSW），O(log N) 查询速度
- 支持 where 过滤的更复杂查询（$eq / $in / $contains 等）
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core import config
from app.rag.base import Document, QueryResult, VectorStore

logger = logging.getLogger(__name__)


class ChromaStore(VectorStore):
    """ChromaDB 封装。首次调用时懒加载 chromadb，未安装时抛出明确错误。"""

    def __init__(
        self,
        persist_dir: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.persist_dir = persist_dir or config.VECTOR_STORE_PERSIST_DIR
        self.default_collection = collection_name or config.VECTOR_STORE_COLLECTION
        self._client = None
        logger.info("ChromaStore 初始化，persist_dir=%s", self.persist_dir)

    def _ensure_client(self):
        """懒加载 chromadb 客户端。"""
        if self._client is not None:
            return self._client
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "ChromaStore 需要 chromadb 依赖。运行 `pip install chromadb` 后再试。"
            ) from exc

        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.persist_dir)
        return self._client

    def _get_or_create(self, collection: str | None):
        name = collection or self.default_collection
        client = self._ensure_client()
        return client.get_or_create_collection(name=name)

    # ---- VectorStore 实现 ----

    def upsert(self, documents: list[Document], collection: str | None = None) -> None:
        col = self._get_or_create(collection)
        col.upsert(
            ids=[d.id for d in documents],
            embeddings=[d.vector for d in documents],
            documents=[d.text for d in documents],
            metadatas=[d.metadata or {} for d in documents],
        )

    def query(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        where: dict | None = None,
        collection: str | None = None,
    ) -> list[QueryResult]:
        col = self._get_or_create(collection)
        kwargs: dict = {
            "query_embeddings": [vector],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)

        # Chroma 距离越小越相似（L2 distance），转成 similarity = 1 / (1 + dist)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]

        out: list[QueryResult] = []
        for _id, text, meta, dist in zip(ids, docs, metas, distances):
            score = 1.0 / (1.0 + dist) if dist is not None else 0.0
            out.append(
                QueryResult(
                    document=Document(
                        id=_id,
                        text=text or "",
                        vector=[],
                        metadata=meta or {},
                    ),
                    score=score,
                )
            )
        return out

    def delete(self, ids: list[str], collection: str | None = None) -> None:
        col = self._get_or_create(collection)
        col.delete(ids=ids)

    def list_collections(self) -> list[str]:
        client = self._ensure_client()
        return [c.name for c in client.list_collections()]

    def reset_collection(self, collection: str | None = None) -> None:
        client = self._ensure_client()
        name = collection or self.default_collection
        client.delete_collection(name=name)

    def get_collection_stats(self, collection: str | None = None) -> dict:
        col = self._get_or_create(collection)
        return {"count": col.count()}
