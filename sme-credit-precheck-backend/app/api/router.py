from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, require_roles
from app.api import (
    applications,
    assistant,
    auth,
    chat,
    frontend_logs,
    materials,
    qa,
    reports,
    reviews,
    risk,
    tasks,
)
from app.models.enums import UserRole

api_router = APIRouter()

# 认证接口无需登录态
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 前端日志上报：登录前后都可能触发，不做鉴权
api_router.include_router(frontend_logs.router, tags=["前端日志"])

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
api_router.include_router(
    tasks.router, prefix="/tasks", tags=["后台任务"], dependencies=auth_required
)

# 风控复核记录查询为只读接口，登录即可访问
api_router.include_router(
    risk.read_router, prefix="/risk", tags=["风控复核"], dependencies=auth_required
)

# 风控队列仅风控人员与管理员可访问
api_router.include_router(
    risk.router,
    prefix="/risk",
    tags=["风控复核"],
    dependencies=[Depends(require_roles(UserRole.RISK, UserRole.ADMIN))],
)

# 政策问答：两种角色都可访问，只读知识库
api_router.include_router(
    qa.router, prefix="/qa", tags=["政策问答"], dependencies=[Depends(get_current_user)]
)

# 授信助手：两种角色都可访问，只读本人名下业务数据
api_router.include_router(
    assistant.router,
    prefix="/assistant",
    tags=["授信助手"],
    dependencies=[Depends(get_current_user)],
)

# 统一对话入口：按问题自动分流政策问答 / 授信助手
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["智能问答"],
    dependencies=[Depends(get_current_user)],
)
