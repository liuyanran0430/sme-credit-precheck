from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.review import RiskReview
from app.schemas.application import ApplicationRead
from app.schemas.review import RiskDecisionCreate, RiskReviewRead

router = APIRouter()


@router.get(
    "/queue",
    response_model=list[ApplicationRead],
    summary="查询风控复核队列",
    description="返回所有处于待风控复核状态的申请。",
)
def list_risk_queue(db: Session = Depends(get_db)) -> list[ApplicationRead]:
    rows = db.scalars(
        select(Application)
        .where(Application.status == ApplicationStatus.RISK)
        .order_by(Application.id.desc())
    ).all()
    return list(rows)


@router.get(
    "/{app_no}/reviews",
    response_model=list[RiskReviewRead],
    summary="查询风控复核记录",
)
def list_risk_reviews(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> list[RiskReviewRead]:
    rows = db.scalars(
        select(RiskReview).where(RiskReview.app_id == app.id).order_by(RiskReview.id.desc())
    ).all()
    return list(rows)


@router.post(
    "/{app_no}/decision",
    response_model=RiskReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="提交风控复核决策",
    description="录入风控决策结论与缓释条件，并推动申请进入审批或补件。业务逻辑待实现。",
)
def submit_risk_decision(
    app: Application = Depends(get_application_or_404),
    payload: RiskDecisionCreate = Body(...),
    db: Session = Depends(get_db),
) -> RiskReviewRead:
    # TODO: 落库决策记录、按结论更新申请状态
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="风控决策逻辑待实现")
