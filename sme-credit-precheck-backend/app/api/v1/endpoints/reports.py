import logging

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.core.logging import LogContext
from app.models.application import Application
from app.models.material import Material
from app.models.report import AiReport
from app.schemas.report import AiReportGenerateRequest, AiReportRead
from app.services.analyzer import generate_report as build_ai_report
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
    report = db.scalar(
        select(AiReport).where(AiReport.app_id == app.id).order_by(AiReport.id.desc())
    )
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
    report = db.scalar(
        select(AiReport).where(AiReport.app_id == app.id).order_by(AiReport.id.desc())
    )
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
    response_model=AiReportRead,
    status_code=status.HTTP_201_CREATED,
    summary="触发 AI 预审",
    description="材料分类完成后自动执行，也可手动重新触发；生成或更新该申请的预审报告。",
)
def generate_report(
    app: Application = Depends(get_application_or_404),
    payload: AiReportGenerateRequest | None = None,
    db: Session = Depends(get_db),
) -> AiReportRead:
    materials = db.scalars(
        select(Material).where(Material.app_id == app.id).order_by(Material.id.asc())
    ).all()
    return build_ai_report(db, app, materials)
