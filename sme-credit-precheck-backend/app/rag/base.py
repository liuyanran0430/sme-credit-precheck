"""VectorStore 抽象基类 + Document / QueryResult 数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    """要存入向量库的一条文档。"""

    id: str                              # 唯一标识；不传则由后端生成
    text: str                            # 原始文本
    vector: list[float]                 # embedding 向量（调用方生成好传入）
    metadata: dict[str, Any] = field(default_factory=dict)  # 过滤/检索用元数据


@dataclass
class QueryResult:
    """相似度查询返回项。"""

    document: Document
    score: float                         # 相似度分数（越大越相似）


class VectorStore(ABC):
    """向量库统一接口。实现类必须提供 upsert / query / delete。"""

    @abstractmethod
    def upsert(self, documents: list[Document], collection: str | None = None) -> None:
        """插入或更新文档（按 id 判断是插还是更）。"""

    @abstractmethod
    def query(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        collection: str | None = None,
    ) -> list[QueryResult]:
        """按向量相似度查询 top_k 条。where 支持 metadata 过滤。"""

    @abstractmethod
    def delete(self, ids: list[str], collection: str | None = None) -> None:
        """按 id 删除。"""

    @abstractmethod
    def list_collections(self) -> list[str]:
        """列出所有 collection 名。"""

    # ---- 可选能力 ----

    def reset_collection(self, collection: str | None = None) -> None:
        """清空某个 collection 的全部内容（实现类可选重写）。"""
        raise NotImplementedError

    def get_collection_stats(self, collection: str | None = None) -> dict[str, Any]:
        """返回 collection 的统计信息（实现类可选重写）。"""
        raise NotImplementedError
