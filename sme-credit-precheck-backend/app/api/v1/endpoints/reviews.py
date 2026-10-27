from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.models.application import Application
from app.models.review import ManualReview
from app.schemas.review import ManualReviewCreate, ManualReviewRead

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
    description="提交逐项复核结果并推动申请进入风控复核队列。业务逻辑待实现。",
)
def submit_manual_review(
    app: Application = Depends(get_application_or_404),
    payload: ManualReviewCreate = Body(...),
    db: Session = Depends(get_db),
) -> ManualReviewRead:
    # TODO: 校验清单完整性、汇总决策结论、更新申请状态
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="人工复核逻辑待实现")
