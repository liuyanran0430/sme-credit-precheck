"""LangChain 实现：ChatOpenAI + with_structured_output 封装成统一 LLMClient 接口。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.core import config
from app.llm.base import LLMClient, LLMResponse
from app.llm.retry import with_retry

logger = logging.getLogger(__name__)


class LangChainClient(LLMClient):
    """基于 LangChain 的 LLM 封装。

    构造参数全部从 :mod:`app.core.config` 读取（已在 .env 中配置好），
    无需调用方传参。支持所有 OpenAI 兼容接口：
      - OpenAI 原生  → LLM_API_KEY=sk-xxx, LLM_BASE_URL=https://api.openai.com/v1
      - Ollama       → LLM_API_KEY=ollama, LLM_BASE_URL=http://localhost:11434/v1, LLM_MODEL=qwen2.5
      - OpenRouter   → LLM_API_KEY=sk-or-xxx, LLM_BASE_URL=https://openrouter.ai/api/v1
      - DashScope    → LLM_API_KEY=sk-xxx, LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    """

    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        self._chat = ChatOpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=config.LLM_MAX_RETRIES,
        )
        logger.info(
            "LangChainClient initialized, model=%s, base_url=%s",
            config.LLM_MODEL,
            config.LLM_BASE_URL,
        )

        # Embedding：没配 EMBEDDING_MODEL 就懒加载（调用 embed 时才报错）
        self._embeddings: OpenAIEmbeddings | None = None

    # ---- LLMClient 接口实现 ----

    def chat(
        self,
        *,
        system: str | None = None,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=user))

        kwargs: dict = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = with_retry(
            lambda: self._chat.invoke(messages, **kwargs),
            operation="chat",
        )
        return LLMResponse(
            content=str(resp.content),
            usage=resp.response_metadata.get("token_usage")
            if resp.response_metadata
            else None,
            model=config.LLM_MODEL,
            raw=resp,
        )

    def structured(
        self,
        *,
        prompt: str,
        schema: type,
        system: str | None = None,
    ) -> object:
        from langchain_core.messages import HumanMessage, SystemMessage

        bound = self._chat.with_structured_output(schema)
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))
        return with_retry(
            lambda: bound.invoke(messages),
            operation="structured",
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not config.EMBEDDING_MODEL:
            logger.warning(
                "EMBEDDING_MODEL 未配置，返回零向量占位。请在 .env 中设置 EMBEDDING_MODEL 启用真实向量化。"
            )
            dim = config.EMBEDDING_DIMENSIONS
            return [[0.0] * dim for _ in texts]

        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings

            self._embeddings = OpenAIEmbeddings(
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                model=config.EMBEDDING_MODEL,
                dimensions=config.EMBEDDING_DIMENSIONS,
            )
        return with_retry(
            lambda: self._embeddings.embed_documents(list(texts)),
            operation="embed",
        )
