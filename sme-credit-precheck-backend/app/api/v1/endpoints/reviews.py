import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_current_user, get_db
from app.core.logging import LogContext
from app.models.application import Application
from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.review import ManualReview
from app.models.user import User
from app.schemas.review import ManualReviewCreate, ManualReviewRead

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "",
    response_model=list[ManualReviewRead],
    summary="查询人工复核记录",
)
def list_manual_reviews(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> list[ManualReviewRead]:
    rows = db.scalars(
        select(ManualReview).where(ManualReview.app_id == app.id).order_by(ManualReview.id.desc())
    ).all()
    return list(rows)


@router.post(
    "",
    response_model=ManualReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="提交人工复核结果",
    description=(
        "提交逐项核验结果与最终复核结论：approve 通过进入风控复核；"
        "supplement 退回补件并将补件说明写入申请；reject 否决申请进入终态。"
    ),
)
def submit_manual_review(
    app: Application = Depends(get_application_or_404),
    payload: ManualReviewCreate = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ManualReviewRead:
    if app.status != ApplicationStatus.MANUAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前申请不在待人工核验状态",
        )

    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="复核清单不能为空，请先完成 AI 预审",
        )

    if payload.decision == "approve":
        decision = ReviewDecision.PASS
        new_status = ApplicationStatus.RISK
        app.supplement_note = None
        app.supplement_source = None
    elif payload.decision == "supplement":
        if not payload.supplement_note or not payload.supplement_note.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="退回补件时补件说明不能为空",
            )
        decision = ReviewDecision.REJECT
        new_status = ApplicationStatus.SUPPLEMENT
        app.supplement_note = payload.supplement_note.strip()
        app.supplement_source = "manual"
    else:
        decision = ReviewDecision.DENY
        new_status = ApplicationStatus.REJECTED
        app.supplement_note = None
        app.supplement_source = None

    app.status = new_status

    with LogContext(app_no=app.app_no, user=user.username):
        logger.info(
            "人工复核提交, app_no=%s, 复核人=%s, 决策=%s, 核验项数=%d, 状态流转→%s",
            app.app_no,
            user.username,
            payload.decision,
            len(payload.items),
            new_status.value,
        )
        if payload.decision == "supplement":
            logger.info(
                "人工复核退回补件, app_no=%s, 来源=manual, 补件说明=%s",
                app.app_no,
                (payload.supplement_note or "")[:50],
            )

    review = ManualReview(
        app_id=app.id,
        reviewer=user.full_name,
        decision=decision,
        checklist_result=[item.model_dump() for item in payload.items],
        comment=payload.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
