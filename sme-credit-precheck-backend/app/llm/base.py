"""LLM 抽象基类：定义 chat / structured / embed 三种能力的统一协议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """LLM 响应的通用容器，屏蔽不同 SDK 的返回格式。"""

    content: str                       # 原始文本内容
    usage: dict[str, int] | None = None  # token 用量（prompt_tokens / completion_tokens / total_tokens）
    model: str | None = None           # 实际使用的模型名
    raw: Any = None                    # 原始 SDK 返回（调试用）


class LLMClient(ABC):
    """LLM 统一接口。实现类必须提供 chat / structured / embed。"""

    @abstractmethod
    def chat(
        self,
        *,
        system: str | None = None,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """一次性问答：system + user → 单轮回复。"""

    @abstractmethod
    def structured(
        self,
        *,
        prompt: str,
        schema: type,
        system: str | None = None,
    ) -> Any:
        """结构化输出：prompt + schema → 直接反序列化为 schema 实例。"""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成 embedding 向量，返回 shape=(len(texts), dim) 的列表。"""
