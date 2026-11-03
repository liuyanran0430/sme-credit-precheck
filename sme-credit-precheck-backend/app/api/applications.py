"""申请管理 endpoints：只负责收发请求与参数校验，DB 读写全部调 repositories。"""

import logging
import shutil
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_current_user, get_db
from app.core import config
from app.core.logging import LogContext, mask_amount, mask_credit_code
from app.models.application import Application
from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.user import User
from app.repositories import (
    ApplicationRepository,
    MaterialRepository,
    ReviewRepository,
)
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEdit,
    ApplicationListPage,
    ApplicationRead,
    ApplicationUpdate,
)
from app.services.analyzer import generate_report

logger = logging.getLogger(__name__)

router = APIRouter()

# 贷款类型 → 申请编号前缀
PRODUCT_NO_PREFIX = {
    "普惠小微经营贷": "AP",
    "小微快贷": "AK",
    "经营性抵押贷": "AJ",
    "科技e贷": "AE",
}


@router.get(
    "",
    response_model=ApplicationListPage,
    summary="分页查询授信申请",
    description="支持按状态、贷款类型、关键字（申请编号 / 企业名称）筛选，按创建时间倒序返回；"
    "响应附带全量各状态申请数量。",
)
def list_applications(
    status_filter: ApplicationStatus | None = Query(None, alias="status", description="申请状态"),
    product: str | None = Query(None, description="贷款类型"),
    keyword: str | None = Query(None, description="申请编号或企业名称关键字"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> ApplicationListPage:
    repo = ApplicationRepository(db)
    rows, total, status_counts = repo.list_paginated(
        status_filter=status_filter,
        product=product,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApplicationListPage(
        items=rows,
        total=total,
        page=page,
        page_size=page_size,
        status_counts=status_counts,
    )


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

    repo = ApplicationRepository(db)
    app_no = repo.next_app_no(prefix)

    with LogContext(app_no=app_no, user=user.username):
        try:
            application = repo.create(
                app_no=app_no,
                company_name=payload.company_name.strip(),
                credit_code=payload.credit_code.upper(),
                amount=Decimal(str(payload.amount)),
                product=product,
                manager_name=user.full_name or user.username,
            )
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="申请编号已存在，请重新提交",
            ) from None

        # 注意：Application.amount 已是万元单位，直接格式化避免与 mask_amount 的元→万转换重复
        logger.info(
            "创建申请, app_no=%s, 企业=%s, 信用代码=%s, 产品=%s, 金额=%s万, 客户经理=%s",
            application.app_no,
            application.company_name,
            mask_credit_code(str(application.credit_code)),
            application.product,
            int(float(application.amount)),
            application.manager_name,
        )
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
    changed_fields: list[str] = []
    for field, value in changes.items():
        normalized = value.strip() if isinstance(value, str) else value
        if getattr(app, field) != normalized:
            setattr(app, field, normalized)
            changed_fields.append(field)

    if not changed_fields:
        return app

    with LogContext(app_no=app.app_no):
        logger.info("编辑申请, app_no=%s, 修改字段=%s", app.app_no, changed_fields)

    app_repo = ApplicationRepository(db)
    mat_repo = MaterialRepository(db)
    app_repo.flush()
    materials = mat_repo.list_by_app(app.id)
    generate_report(db, app, materials)
    app_repo.commit()
    app_repo.refresh(app)
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
    with LogContext(app_no=app.app_no):
        logger.info("删除申请, app_no=%s", app.app_no)

    ApplicationRepository(db).delete_cascade(app)

    # 清理该申请的上传文件目录
    shutil.rmtree(Path(config.UPLOAD_DIR) / app.app_no, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
