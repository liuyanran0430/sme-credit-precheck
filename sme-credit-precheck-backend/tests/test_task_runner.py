"""task_runner 单元测试：提交、去重、失败记录、过期清理。不依赖外部资源。"""

import threading
import time

from app.services import task_runner


def _wait_done(request_id: str, timeout: float = 5.0) -> dict | None:
    """轮询等待任务脱离 running 状态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = task_runner.get(request_id)
        if task is None or task["status"] != task_runner.STATUS_RUNNING:
            return task
        time.sleep(0.05)
    return task_runner.get(request_id)


def setup_function() -> None:
    with task_runner._lock:
        task_runner._TASKS.clear()


def test_submit_runs_to_done() -> None:
    finished = threading.Event()

    def fn(db) -> None:
        finished.set()

    rid = task_runner.submit("AP00000001", task_runner.TASK_TYPE_MATERIALS_UPLOAD, fn)
    assert rid

    task = _wait_done(rid)
    assert finished.is_set()
    assert task is not None
    assert task["status"] == task_runner.STATUS_DONE
    assert task["error"] is None
    assert task["app_no"] == "AP00000001"
    assert task["task_type"] == task_runner.TASK_TYPE_MATERIALS_UPLOAD


def test_submit_dedupes_running_task() -> None:
    blocker = threading.Event()

    def slow_fn(db) -> None:
        blocker.wait(timeout=2)

    rid1 = task_runner.submit("AP00000002", task_runner.TASK_TYPE_REPORT_GENERATE, slow_fn)
    rid2 = task_runner.submit("AP00000002", task_runner.TASK_TYPE_REPORT_GENERATE, slow_fn)
    assert rid1 == rid2

    # 不同 task_type 不去重
    rid3 = task_runner.submit("AP00000002", task_runner.TASK_TYPE_MATERIALS_UPLOAD, slow_fn)
    assert rid3 != rid1

    blocker.set()
    _wait_done(rid1)
    _wait_done(rid3)


def test_failed_task_records_error() -> None:
    def bad_fn(db) -> None:
        raise RuntimeError("LLM 调用失败")

    rid = task_runner.submit("AP00000003", task_runner.TASK_TYPE_REPORT_GENERATE, bad_fn)
    task = _wait_done(rid)
    assert task is not None
    assert task["status"] == task_runner.STATUS_FAILED
    assert "LLM 调用失败" in task["error"]


def test_unknown_request_id_returns_none() -> None:
    assert task_runner.get("nonexistent") is None


def test_expired_finished_task_is_purged() -> None:
    rid = task_runner.submit("AP00000004", task_runner.TASK_TYPE_MATERIALS_UPLOAD, lambda db: None)
    task = _wait_done(rid)
    assert task is not None and task["status"] == task_runner.STATUS_DONE

    # 手动把完成时间调到 TTL 之前，触发惰性清理
    with task_runner._lock:
        task_runner._TASKS[rid]["finished_at"] = time.time() - task_runner._TASK_TTL_SECONDS - 1
    assert task_runner.get(rid) is None
