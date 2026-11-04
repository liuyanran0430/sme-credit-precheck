"""AI 预审报告 endpoints：DB 查询全部调 ReportRepository。"""

import logging

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.core.logging import LogContext
from app.models.application import Application
from app.repositories import ReportRepository
from app.schemas.report import AiReportGenerateRequest, AiReportRead
from app.schemas.task import TaskSubmitResponse
from app.services import task_runner
from app.services.analyzer import generate_report_for_app
from app.services.report_pdf import get_report_pdf

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=AiReportRead,
    summary="查询 AI 预审报告",
    description="返回该申请最新一版 AI 预审报告。",
)
def get_latest_report(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> AiReportRead:
    report = ReportRepository(db).get_latest_by_app(app.id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预审报告尚未生成")
    return report


@router.get(
    "/export",
    summary="导出 AI 预审报告",
    description="将最新一版 AI 预审报告导出为 PDF 文件，内容取自已落库的报告快照。",
    responses={404: {"description": "预审报告尚未生成"}},
)
def export_report(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> Response:
    report = ReportRepository(db).get_latest_by_app(app.id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预审报告尚未生成")

    with LogContext(app_no=app.app_no):
        logger.info("导出预审报告, app_no=%s", app.app_no)

    filename = f"AI预审报告_{app.app_no}.pdf"
    return Response(
        content=get_report_pdf(app, report),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=report_{app.app_no}.pdf; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post(
    "/generate",
    response_model=TaskSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="触发 AI 预审（异步任务）",
    description=(
        "立即返回 request_id；预审报告在后台线程生成，"
        "前端通过 GET /tasks/{request_id} 轮询任务状态，完成后调用 GET report 获取报告。"
    ),
)
def generate_report(
    app: Application = Depends(get_application_or_404),
    payload: AiReportGenerateRequest | None = None,
) -> TaskSubmitResponse:
    request_id = task_runner.submit(
        app.app_no,
        task_runner.TASK_TYPE_REPORT_GENERATE,
        lambda db: generate_report_for_app(db, app.id),
    )
    return TaskSubmitResponse(request_id=request_id, app_no=app.app_no)
