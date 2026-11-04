"""后台任务状态查询 endpoint。"""

from fastapi import APIRouter, HTTPException, status

from app.schemas.task import TaskStatusRead
from app.services import task_runner

router = APIRouter()


@router.get(
    "/{request_id}",
    response_model=TaskStatusRead,
    summary="查询后台任务状态",
    description="按 request_id 轮询异步任务（材料上传 OCR/分类、AI 预审）的执行状态。",
    responses={404: {"description": "任务不存在或已过期"}},
)
def get_task_status(request_id: str) -> TaskStatusRead:
    task = task_runner.get(request_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或已过期"
        )
    return TaskStatusRead(**task)
