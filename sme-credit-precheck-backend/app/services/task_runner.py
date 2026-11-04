"""轻量级后台任务执行器：LLM 耗时接口的异步化支撑。

设计要点：
- 内存 registry（dict + threading.Lock），单进程 uvicorn 适用；
  任务进度细节落库在 materials/applications 表，这里只承载任务生命周期。
- 同一 app_no + task_type 已有 running 任务时直接返回现有 request_id，防止重复提交。
- 后台线程内新建 SessionLocal，不跨线程复用请求级 session。
- 通过 contextvars.copy_context() 继承提交线程的日志上下文（trace_id 等）。
- 任务结束（done/failed）后保留 TTL 供前端轮询，超时惰性清理。
"""

import contextvars
import logging
import threading
import time
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.logging import LogContext
from app.models.session import SessionLocal

logger = logging.getLogger(__name__)

TASK_TYPE_MATERIALS_UPLOAD = "materials_upload"
TASK_TYPE_REPORT_GENERATE = "report_generate"

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_TASK_TTL_SECONDS = 600  # 任务结束后保留 10 分钟供前端轮询结果

_TASKS: dict[str, dict] = {}
_lock = threading.Lock()


def _purge_expired(now: float) -> None:
    """清理已结束且超过 TTL 的任务（调用时需已持有 _lock）。"""
    expired = [
        rid
        for rid, t in _TASKS.items()
        if t["status"] != STATUS_RUNNING and now - t["finished_at"] > _TASK_TTL_SECONDS
    ]
    for rid in expired:
        del _TASKS[rid]


def submit(
    app_no: str,
    task_type: str,
    fn: Callable[[Session], None],
) -> str:
    """提交后台任务，返回 request_id。

    fn 接收一个新建的数据库 session，由 runner 负责关闭。
    同 app_no + task_type 存在 running 任务时，直接返回现有 request_id（幂等去重）。
    """
    with _lock:
        _purge_expired(time.time())
        for rid, t in _TASKS.items():
            if (
                t["app_no"] == app_no
                and t["type"] == task_type
                and t["status"] == STATUS_RUNNING
            ):
                logger.info(
                    "任务去重：%s 已有运行中的 %s 任务 request_id=%s", app_no, task_type, rid
                )
                return rid

        request_id = uuid.uuid4().hex
        _TASKS[request_id] = {
            "type": task_type,
            "app_no": app_no,
            "status": STATUS_RUNNING,
            "error": None,
            "finished_at": 0.0,
        }

    # 继承提交线程的日志上下文（trace_id / app_no 等 ContextVar），
    # 并在其中注入本次任务的 request_id —— llm_runs 与日志都据此关联，
    # 该值即接口返回给前端的 request_id。
    ctx = contextvars.copy_context()

    def _body() -> None:
        LogContext.set(request_id=request_id)
        db = SessionLocal()
        try:
            fn(db)
        finally:
            db.close()

    def _run() -> None:
        try:
            ctx.run(_body)
        except Exception as exc:  # noqa: BLE001 - 任务失败记录状态，不抛出
            logger.warning(
                "后台任务失败, request_id=%s, type=%s, app_no=%s, 错误=%s",
                request_id,
                task_type,
                app_no,
                exc,
            )
            with _lock:
                t = _TASKS.get(request_id)
                if t is not None:
                    t["status"] = STATUS_FAILED
                    t["error"] = str(exc)
                    t["finished_at"] = time.time()
        else:
            with _lock:
                t = _TASKS.get(request_id)
                if t is not None:
                    t["status"] = STATUS_DONE
                    t["finished_at"] = time.time()
            logger.info(
                "后台任务完成, request_id=%s, type=%s, app_no=%s",
                request_id,
                task_type,
                app_no,
            )

    threading.Thread(target=_run, daemon=True, name=f"task-{task_type}-{app_no}").start()
    logger.info("后台任务已提交, request_id=%s, type=%s, app_no=%s", request_id, task_type, app_no)
    return request_id


def get(request_id: str) -> dict | None:
    """查询任务状态；不存在或已过期返回 None。"""
    with _lock:
        _purge_expired(time.time())
        t = _TASKS.get(request_id)
        if t is None:
            return None
        return {
            "request_id": request_id,
            "task_type": t["type"],
            "app_no": t["app_no"],
            "status": t["status"],
            "error": t["error"],
        }
