from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, require_roles
from app.api.v1.endpoints import applications, auth, materials, reports, reviews, risk
from app.models.enums import UserRole

api_router = APIRouter()

# 认证接口无需登录态
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 业务接口需登录后访问
auth_required = [Depends(get_current_user)]
api_router.include_router(
    applications.router, prefix="/applications", tags=["申请管理"], dependencies=auth_required
)
api_router.include_router(
    materials.router,
    prefix="/applications/{app_no}/materials",
    tags=["材料管理"],
    dependencies=auth_required,
)
api_router.include_router(
    reports.router,
    prefix="/applications/{app_no}/report",
    tags=["AI 预审"],
    dependencies=auth_required,
)
api_router.include_router(
    reviews.router,
    prefix="/applications/{app_no}/reviews",
    tags=["人工复核"],
    dependencies=auth_required,
)

# 风控队列仅风控人员与管理员可访问
api_router.include_router(
    risk.router,
    prefix="/risk",
    tags=["风控复核"],
    dependencies=[Depends(require_roles(UserRole.RISK, UserRole.ADMIN))],
)
