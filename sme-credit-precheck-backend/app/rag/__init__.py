"""RAG 向量库封装层。

设计原则：
- 统一 :class:`VectorStore` 抽象接口（upsert / query / delete / list_collections）
- 默认实现 :class:`InMemoryStore`——进程内 dict 存向量，零依赖，适合开发和测试
- :class:`ChromaStore` 占位实现——pip install chromadb 后可用，持久化到磁盘
- 上层（未来的规则检索 / 风控知识库）只依赖 VectorStore 抽象，换后端零改动

与 app/llm 的关系：
- VectorStore.upsert / query 需要调用 embedding 生成向量
- 但 VectorStore 不直接 import LLMClient，调用方自己 embed 完传进来（解耦）

数据模型：
    Document = {
        id: str,                 # 唯一标识（自动生成或业务主键）
        text: str,               # 原文
        vector: list[float],     # embedding 向量（调用方自行生成）
        metadata: dict[str, any] # 过滤字段（如 category="规则", source="国家"）
    }
"""

from .base import Document, QueryResult, VectorStore
from .memory_store import InMemoryStore
from .chroma_store import ChromaStore
from .factory import get_vector_store
from .kb_retriever import (
    KB_CASES,
    KB_MATERIAL_REVIEW,
    KB_POLICY,
    KB_RULE_CONFIG,
    KnowledgeHit,
    retrieve_material_hints,
    retrieve_rule_basis,
    search,
)

__all__ = [
    "Document",
    "QueryResult",
    "VectorStore",
    "InMemoryStore",
    "ChromaStore",
    "get_vector_store",
    "KB_POLICY",
    "KB_MATERIAL_REVIEW",
    "KB_RULE_CONFIG",
    "KB_CASES",
    "KnowledgeHit",
    "search",
    "retrieve_rule_basis",
    "retrieve_material_hints",
]
