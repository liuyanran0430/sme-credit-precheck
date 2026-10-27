from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.models.application import Application
from app.models.material import Material
from app.models.report import AiReport
from app.schemas.ai_analysis import (
    CompletenessResult,
    MaterialAnalysisRequest,
    MaterialAnalysisResponse,
)
from app.schemas.ai_errors import AiErrorResponse
from app.schemas.report import AiReportGenerateRequest, AiReportRead
from app.services.analyzer import analyze_completeness, generate_report as build_ai_report

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
    "/completeness",
    response_model=CompletenessResult,
    summary="材料完整性分析",
    description=(
        "按必备材料清单、内容可读性与特殊要求（流水覆盖超过 6 个月、财务报表三表齐全）"
        "判断材料完整性；一致性校验暂未接入。"
    ),
)
def get_completeness(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> CompletenessResult:
    materials = db.scalars(
        select(Material).where(Material.app_id == app.id).order_by(Material.id.asc())
    ).all()
    return analyze_completeness(materials)


@router.post(
    "/analyze",
    response_model=MaterialAnalysisResponse,
    summary="AI 材料分析",
    description=(
        "执行材料完整性与一致性判断、准入规则匹配、风险信号汇总，"
        "并输出低置信 / 规则冲突项。业务逻辑待实现。"
    ),
    responses={400: {"model": AiErrorResponse}},
)
def analyze_materials(
    payload: MaterialAnalysisRequest,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> MaterialAnalysisResponse:
    # TODO: 校验 payload.context.app_no 与路径参数一致，
    #       调用 services.analyzer.analyze_materials 并落库 AiReport
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="AI 材料分析逻辑待实现")


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
