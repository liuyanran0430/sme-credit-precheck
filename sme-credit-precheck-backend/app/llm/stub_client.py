"""StubClient：本地开发时未配 API Key 的 fallback。

返回确定性假结果（LLMResponse 带 content='[stub] ...' 前缀），
embed 用零向量占位。不用于生产。
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence

from app.core import config
from app.llm.base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class StubClient(LLMClient):
    """不调任何外部服务，返回占位结果，方便无 API Key 时跑通全流程。"""

    def __init__(self) -> None:
        logger.warning(
            "StubClient activated — LLM_API_KEY 未配置或无效。"
            "所有 LLM 调用将返回占位结果，仅用于本地开发冒烟测试。"
        )

    def chat(
        self,
        *,
        system: str | None = None,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # 用输入的 hash 生成一个伪稳定的回复，避免每次都一样
        digest = hashlib.md5((user or "").encode()).hexdigest()[:8]
        return LLMResponse(
            content=f"[stub] 占位回复（hash={digest}）。未配置 LLM_API_KEY 时返回假结果。",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            model="stub",
        )

    def structured(
        self,
        *,
        prompt: str,
        schema: type,
        system: str | None = None,
        method: str = "function_calling",
    ) -> object:
        # 返回 schema 的零值实例（pydantic 用 model_construct，dataclass 无参构造）
        if hasattr(schema, "model_construct"):
            return schema.model_construct()
        if hasattr(schema, "__dataclass_fields__"):
            import dataclasses

            return dataclasses.make_dataclass(schema.__name__, [])()
        return None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # 零向量占位，维度取配置默认值
        dim = config.EMBEDDING_DIMENSIONS
        return [[0.0] * dim for _ in texts]
