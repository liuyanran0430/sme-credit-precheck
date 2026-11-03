"""VectorStore 工厂：根据 config.VECTOR_STORE_BACKEND 自动选择实现。"""

from __future__ import annotations

import logging

from app.core import config
from app.rag.base import VectorStore

logger = logging.getLogger(__name__)

_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """获取全局共享的 VectorStore（单例）。"""
    global _store
    if _store is not None:
        return _store

    backend = config.VECTOR_STORE_BACKEND.lower()
    if backend == "memory":
        from app.rag.memory_store import InMemoryStore

        _store = InMemoryStore()
        logger.info("VectorStore backend=memory（进程内，重启丢失）")
    elif backend == "chroma":
        from app.rag.chroma_store import ChromaStore

        _store = ChromaStore()
        logger.info("VectorStore backend=chroma（磁盘持久化）")
    elif backend == "milvus":
        # 留占位，未来接 pymilvus
        raise NotImplementedError("milvus backend 尚未实现，请先用 memory 或 chroma")
    else:
        raise ValueError(
            f"未知的 VECTOR_STORE_BACKEND={backend}，可选值：memory | chroma | milvus"
        )

    return _store
