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

        # max_retries=0：禁掉 langchain 内置重试，统一走 with_retry（按错误类型分级）
        self._chat = ChatOpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=0,
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
        method: str = "function_calling",
    ) -> object:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.llm.retry import (
            LLMContextError,
            LLMJSONParseError,
            _is_context_overflow,
            _is_json_parse_error,
        )

        bound = self._chat.with_structured_output(schema, method=method)
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        # 第一次尝试：正常调用（网络/429/超时由 with_retry 处理）
        try:
            return with_retry(
                lambda: bound.invoke(messages),
                operation="structured",
            )
        except Exception as exc:  # noqa: BLE001 — 区分错误类型
            # JSON 解析失败 → 重试一次（第二次通常模型会修正）
            if _is_json_parse_error(exc):
                logger.warning("LLM 结构化输出 JSON 解析失败，重试一次: %s", exc)
                try:
                    return with_retry(
                        lambda: bound.invoke(messages),
                        operation="structured_retry",
                    )
                except Exception as retry_exc:  # noqa: BLE001
                    if _is_json_parse_error(retry_exc):
                        raise LLMJSONParseError(
                            f"连续两次 JSON 解析失败，降级处理: {retry_exc}"
                        ) from retry_exc
                    raise

            # 上下文超限 → 抛出专用异常，由上层截断后重试
            if _is_context_overflow(exc):
                raise LLMContextError(
                    f"上下文超限（{len(prompt)} 字符），需截断后重试"
                ) from exc

            raise

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not config.EMBEDDING_MODEL:
            logger.warning(
                "EMBEDDING_MODEL 未配置，返回零向量占位。请在 .env 中设置 EMBEDDING_MODEL 启用真实向量化。"
            )
            dim = config.EMBEDDING_DIMENSIONS
            return [[0.0] * dim for _ in texts]

        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings

            # dimensions 仅在显式配置为正数时传递：
            # 部分模型（如 BAAI/bge-m3）不支持该参数，传了会返回 400
            kwargs: dict[str, object] = {
                "api_key": config.EMBEDDING_API_KEY,
                "base_url": config.EMBEDDING_BASE_URL,
                "model": config.EMBEDDING_MODEL,
            }
            if config.EMBEDDING_DIMENSIONS > 0:
                kwargs["dimensions"] = config.EMBEDDING_DIMENSIONS
            self._embeddings = OpenAIEmbeddings(**kwargs)  # type: ignore[arg-type]
        return with_retry(
            lambda: self._embeddings.embed_documents(list(texts)),
            operation="embed",
        )
