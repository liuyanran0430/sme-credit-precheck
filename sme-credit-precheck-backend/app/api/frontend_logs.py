"""前端日志上报接口：接收前端 logger 上报的日志，写入 frontend-YYYY-MM-DD.log。

前端通过 logger.js 批量上报 warn/error 级别日志；
调用 LLM 相关接口的日志会额外携带 request_id，便于和后端日志按 request_id 串联排查。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 和后端日志同目录：sme-credit-precheck-backend/logs/
_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()


class FrontendLogEntry(BaseModel):
    timestamp: str = Field(..., description="ISO 时间戳")
    level: str = Field(..., description="日志级别 debug/info/warn/error")
    message: str = Field(..., description="日志消息")
    request_id: str | None = Field(default=None, description="LLM 相关接口返回的 request_id")
    extra: dict[str, Any] | None = Field(default=None, description="附加上下文")


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogEntry]


def _frontend_log_path() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return _LOGS_DIR / f"frontend-{today}.log"


@router.post("/frontend-logs", status_code=204)
def receive_frontend_logs(batch: FrontendLogBatch) -> None:
    """接收前端批量上报的日志，追加写入 frontend-YYYY-MM-DD.log。"""
    if not batch.entries:
        return

    path = _frontend_log_path()
    lines: list[str] = []
    for entry in batch.entries:
        # 格式对齐后端日志：时间 级别 request_id=xxx 消息 {extra}
        parts = [entry.timestamp, entry.level.upper().ljust(7)]
        if entry.request_id:
            parts.append(f"request_id={entry.request_id}")
        parts.append(entry.message)
        if entry.extra:
            try:
                parts.append(json.dumps(entry.extra, ensure_ascii=False))
            except (TypeError, ValueError):
                parts.append("[unserializable]")
        lines.append(" ".join(parts))

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("写入前端日志失败: %s", exc)
