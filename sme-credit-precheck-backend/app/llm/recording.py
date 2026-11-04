"""LLM 调用记录器：包装 LLMClient，每次调用写入 llm_runs 表。

设计要点：
- 用独立 SessionLocal 写库，不污染请求事务
- 记录失败不影响 LLM 调用本身（best-effort）
- 从 LogContext 取 request_id，与异步任务接口返回给前端的一致
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from app.core import config
from app.core.logging import LogContext
from app.llm.base import LLMClient, LLMResponse
from app.models.llm_run import LLMRun
from app.models.session import SessionLocal

logger = logging.getLogger(__name__)


def _write_run(
    *,
    model: str | None,
    method: str,
    latency_ms: float,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_message: str | None = None,
) -> None:
    """异步式写入一条 LLM 调用记录。失败仅打日志，不抛异常。"""
    try:
        request_id = LogContext.get().get("request_id")
        with SessionLocal() as db:
            db.add(
                LLMRun(
                    model=model or config.LLM_MODEL,
                    method=method,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=round(latency_ms, 2),
                    status=status,
                    error_message=error_message,
                    request_id=request_id,
                )
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 — 记录失败不能影响业务
        logger.warning("写入 llm_runs 失败: %s", exc)


class RecordingLLMClient(LLMClient):
    """透明包装：把调用委托给 inner，同时记录遥测。"""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    def chat(
        self,
        *,
        system: str | None = None,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        start = time.perf_counter()
        try:
            resp = self._inner.chat(
                system=system, user=user, temperature=temperature, max_tokens=max_tokens
            )
            latency = (time.perf_counter() - start) * 1000
            usage = resp.usage or {}
            _write_run(
                model=resp.model,
                method="chat",
                latency_ms=latency,
                status="success",
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            return resp
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            _write_run(
                model=config.LLM_MODEL,
                method="chat",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
            )
            raise

    def structured(
        self,
        *,
        prompt: str,
        schema: type,
        system: str | None = None,
        method: str = "function_calling",
    ) -> Any:
        start = time.perf_counter()
        try:
            result = self._inner.structured(
                prompt=prompt, schema=schema, system=system, method=method
            )
            latency = (time.perf_counter() - start) * 1000
            _write_run(
                model=config.LLM_MODEL,
                method="structured",
                latency_ms=latency,
                status="success",
            )
            return result
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            _write_run(
                model=config.LLM_MODEL,
                method="structured",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
            )
            raise

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        start = time.perf_counter()
        try:
            vectors = self._inner.embed(texts)
            latency = (time.perf_counter() - start) * 1000
            _write_run(
                model=config.EMBEDDING_MODEL or config.LLM_MODEL,
                method="embed",
                latency_ms=latency,
                status="success",
                total_tokens=len(texts),
            )
            return vectors
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            _write_run(
                model=config.EMBEDDING_MODEL or config.LLM_MODEL,
                method="embed",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
            )
            raise
