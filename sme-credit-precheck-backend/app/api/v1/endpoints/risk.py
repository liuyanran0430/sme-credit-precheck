import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_current_user, get_db
from app.core.logging import LogContext
from app.models.application import Application
from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.review import RiskReview
from app.models.user import User
from app.schemas.application import ApplicationRead
from app.schemas.review import RiskDecisionCreate, RiskReviewRead

logger = logging.getLogger(__name__)
router = APIRouter()

# 只读查询路由：登录即可访问（申请详情页需读取风控复核记录定位被拒环节）
read_router = APIRouter()


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
    # 曾被风控退回补件的申请标记 risk_returned，便于风控人员识别"补齐后回流"的单子
    returned_app_ids = set(
        db.scalars(
            select(RiskReview.app_id).where(RiskReview.decision == ReviewDecision.REJECT)
        ).all()
    )
    for row in rows:
        row.risk_returned = row.id in returned_app_ids
    return list(rows)


@read_router.get(
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
    description=(
        "落库风控决策记录并流转申请状态："
        "通过 → 已审批；退回补件 → 待补件；拒绝 → 已否决。"
    ),
)
def submit_risk_decision(
    app: Application = Depends(get_application_or_404),
    payload: RiskDecisionCreate = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RiskReviewRead:
    if app.status != ApplicationStatus.RISK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前申请不在待风控复核状态",
        )

    old_status = app.status
    review = RiskReview(
        app_id=app.id,
        reviewer=user.full_name or user.username,
        decision=ReviewDecision(payload.decision),
        opinion=payload.opinion.strip(),
        mitigation=None,
    )
    db.add(review)
    if payload.decision == "pass":
        new_status = ApplicationStatus.APPROVED
        app.supplement_note = None
        app.supplement_source = None
    elif payload.decision == "reject":
        # 风控退回补件：补件说明取风控复核意见，来源标记 risk，补齐后直接回流风控队列
        new_status = ApplicationStatus.SUPPLEMENT
        app.supplement_note = payload.opinion.strip()
        app.supplement_source = "risk"
    else:
        new_status = ApplicationStatus.REJECTED
        app.supplement_note = None
        app.supplement_source = None
    app.status = new_status

    with LogContext(app_no=app.app_no, user=user.username):
        logger.info(
            "风控复核提交, app_no=%s, 风控人=%s, 决策=%s, 状态流转=%s→%s",
            app.app_no,
            user.username,
            payload.decision,
            old_status.value,
            new_status.value,
        )
        if payload.decision == "reject":
            logger.info(
                "风控退回补件, app_no=%s, 来源=risk, 补件说明=%s",
                app.app_no,
                payload.opinion.strip()[:50],
            )

    db.commit()
    db.refresh(review)
    return review
