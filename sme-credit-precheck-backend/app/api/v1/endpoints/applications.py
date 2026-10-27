import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_current_user, get_db
from app.core import config
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.material import Material
from app.models.report import AiReport
from app.models.review import ManualReview, RiskReview
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEdit,
    ApplicationRead,
    ApplicationUpdate,
)
from app.schemas.common import Page
from app.services.analyzer import generate_report

router = APIRouter()

# 贷款类型 → 申请编号前缀
PRODUCT_NO_PREFIX = {
    "普惠小微经营贷": "AP",
    "小微快贷": "AK",
    "经营性抵押贷": "AJ",
    "科技e贷": "AE",
}


def _next_app_no(db: Session, prefix: str) -> str:
    """按编号前缀生成同类型申请的下一个编号。"""
    latest_no = db.scalar(
        select(Application.app_no)
        .where(Application.app_no.like(f"{prefix}%"))
        .order_by(Application.app_no.desc())
        .limit(1)
    )
    tail = latest_no[len(prefix) :] if latest_no else ""
    seq = int(tail) + 1 if tail.isdigit() else 1
    return f"{prefix}{seq:08d}"


@router.get(
    "",
    response_model=Page[ApplicationRead],
    summary="分页查询授信申请",
    description="支持按状态、关键字（申请编号 / 企业名称）筛选，按创建时间倒序返回。",
)
def list_applications(
    status_filter: ApplicationStatus | None = Query(None, alias="status", description="申请状态"),
    keyword: str | None = Query(None, description="申请编号或企业名称关键字"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> Page[ApplicationRead]:
    stmt = select(Application)
    if status_filter is not None:
        stmt = stmt.where(Application.status == status_filter)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(Application.app_no.ilike(like), Application.company_name.ilike(like))
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Application.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return Page[ApplicationRead](items=list(rows), total=total, page=page, page_size=page_size)


@router.post(
    "",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
    summary="提交新申请",
    description="创建授信申请并写入数据库，客户经理取当前登录用户姓名，申请进入待材料检查状态。",
)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApplicationRead:
    product = payload.product.strip()
    prefix = PRODUCT_NO_PREFIX.get(product)
    if prefix is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的贷款类型：{product}",
        )

    application = Application(
        app_no=_next_app_no(db, prefix),
        company_name=payload.company_name.strip(),
        credit_code=payload.credit_code.upper(),
        amount=Decimal(str(payload.amount)),
        product=product,
        status=ApplicationStatus.CHECK,
        manager_name=user.full_name or user.username,
        submitted_at=datetime.now(),
        ai_summary="申请已提交，等待材料检查与 AI 预审。",
    )
    db.add(application)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="申请编号已存在，请重新提交"
        ) from None
    db.refresh(application)
    return application


@router.get(
    "/{app_no}",
    response_model=ApplicationRead,
    summary="查询申请详情",
)
def get_application(app: Application = Depends(get_application_or_404)) -> ApplicationRead:
    return app


@router.patch(
    "/{app_no}",
    response_model=ApplicationRead,
    summary="修改申请信息",
    description=(
        "修改企业名称、统一社会信用代码、贷款类型、申请金额；"
        "任一字段发生变化时重新生成 AI 预审报告。"
    ),
)
def edit_application(
    payload: ApplicationEdit,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> ApplicationRead:
    changes = payload.model_dump(exclude_none=True)
    changed = False
    for field, value in changes.items():
        normalized = value.strip() if isinstance(value, str) else value
        if getattr(app, field) != normalized:
            setattr(app, field, normalized)
            changed = True

    if not changed:
        return app

    db.flush()
    materials = db.scalars(select(Material).where(Material.app_id == app.id)).all()
    generate_report(db, app, list(materials))
    db.commit()
    db.refresh(app)
    return app


@router.patch(
    "/{app_no}/status",
    response_model=ApplicationRead,
    summary="流转申请状态",
    description="人工复核 / 风控决策后推动申请状态流转。业务逻辑待实现。",
)
def update_application_status(
    app: Application = Depends(get_application_or_404),
    payload: ApplicationUpdate = Body(...),
    db: Session = Depends(get_db),
) -> ApplicationRead:
    # TODO: 校验状态机合法性、写入流转记录
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="状态流转逻辑待实现")


@router.delete(
    "/{app_no}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除申请",
    description="删除申请及其所有关联数据（AI 报告、人工复核、风控复核、材料记录），并清理上传文件。",
)
def delete_application(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> Response:
    for model in (AiReport, ManualReview, RiskReview, Material):
        db.execute(delete(model).where(model.app_id == app.id))
    db.delete(app)
    db.commit()

    # 清理该申请的上传文件目录
    shutil.rmtree(Path(config.UPLOAD_DIR) / app.app_no, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
