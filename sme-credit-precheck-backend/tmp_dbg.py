import time

from app.core.logging import LogContext
from app.services import task_runner

seen = {}


def fn(db) -> None:
    seen["ctx"] = LogContext.get()
    from app.llm.recording import _write_run

    _write_run(model="dbg", method="chat", latency_ms=1.0, status="success")


LogContext.set(trace_id="t-submit")
rid = task_runner.submit("DBGAPP", "dbg", fn)
time.sleep(2)
print("request_id:", rid)
print("子线程 LogContext:", seen.get("ctx"))

from sqlalchemy import text

from app.models.session import engine

with engine.connect() as c:
    rows = list(
        c.execute(
            text("SELECT model, method, request_id FROM llm_runs WHERE model='dbg'")
        )
    )
    print("写入行:", rows)
