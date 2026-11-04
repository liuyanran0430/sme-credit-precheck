"""后台任务相关 schema。"""

from pydantic import BaseModel


class TaskSubmitResponse(BaseModel):
    """异步任务提交响应（202）。"""

    request_id: str
    app_no: str


class TaskStatusRead(BaseModel):
    """任务状态查询响应。"""

    request_id: str
    task_type: str
    app_no: str
    status: str  # running / done / failed
    error: str | None = None
