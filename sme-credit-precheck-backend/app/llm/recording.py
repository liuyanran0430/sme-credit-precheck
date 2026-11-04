"""LLM 调用记录器：包装 LLMClient，每次调用写入 llm_runs 表并输出结构化日志。

设计要点：
- 用独立 SessionLocal 写库，不污染请求事务
- 记录失败不影响 LLM 调用本身（best-effort）
- request_id 从 LogContext 读取，与异步任务接口返回给前端的一致
- 每次调用额外输出一行结构化 JSON 到 llm-YYYY-MM-DD.log，字段覆盖：
  request_id / user_id / session_id / model / prompt_version /
  retrieval_ids / tool_calls / latency_ms / tokens / error_type
- 暂未接入 RAG 与 tool 调用，retrieval_ids、tool_calls 固定为空数组
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.core import config
from app.core.logging import LLM_AUDIT_LOGGER_NAME, LogContext
from app.llm.base import LLMClient, LLMResponse
from app.llm.retry import classify_error_type
from app.models.llm_run import LLMRun
from app.models.session import SessionLocal

logger = logging.getLogger(__name__)
_audit_logger = logging.getLogger(LLM_AUDIT_LOGGER_NAME)


def _ctx_value(key: str) -> object | None:
    """读取 LogContext 中的值；未设置（占位 "-"）时返回 None。"""
    value = LogContext.get().get(key)
    return None if value in (None, "-") else value


def _write_structured_log(
    *,
    model: str,
    latency_ms: float,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_type: str | None = None,
) -> None:
    """输出一行结构化 JSON，写入 llm-YYYY-MM-DD.log。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "request_id": _ctx_value("request_id"),
        "user_id": _ctx_value("user_id"),
        "session_id": _ctx_value("session_id"),
        "model": model,
        "prompt_version": config.LLM_PROMPT_VERSION,
        "retrieval_ids": [],
        "tool_calls": [],
        "latency_ms": round(latency_ms, 2),
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
        },
        "error_type": None if status == "success" else (error_type or "unknown"),
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False))


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
        request_id = _ctx_value("request_id")
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


def _record(
    *,
    model: str | None,
    method: str,
    latency_ms: float,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_message: str | None = None,
    error_type: str | None = None,
) -> None:
    """落库 + 结构化日志，两条通道互不影响。"""
    try:
        _write_structured_log(
            model=model or config.LLM_MODEL,
            latency_ms=latency_ms,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
        )
    except Exception as exc:  # noqa: BLE001 — 日志失败不能影响业务
        logger.warning("输出 LLM 结构化日志失败: %s", exc)

    _write_run(
        model=model,
        method=method,
        latency_ms=latency_ms,
        status=status,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        error_message=error_message,
    )


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
            _record(
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
            _record(
                model=config.LLM_MODEL,
                method="chat",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
                error_type=classify_error_type(exc),
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
            _record(
                model=config.LLM_MODEL,
                method="structured",
                latency_ms=latency,
                status="success",
            )
            return result
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            _record(
                model=config.LLM_MODEL,
                method="structured",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
                error_type=classify_error_type(exc),
            )
            raise

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        start = time.perf_counter()
        try:
            vectors = self._inner.embed(texts)
            latency = (time.perf_counter() - start) * 1000
            _record(
                model=config.EMBEDDING_MODEL or config.LLM_MODEL,
                method="embed",
                latency_ms=latency,
                status="success",
                total_tokens=len(texts),
            )
            return vectors
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            _record(
                model=config.EMBEDDING_MODEL or config.LLM_MODEL,
                method="embed",
                latency_ms=latency,
                status="failure",
                error_message=str(exc)[:500],
                error_type=classify_error_type(exc),
            )
            raise
