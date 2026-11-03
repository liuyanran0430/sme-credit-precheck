"""FastAPI 依赖注入：数据库会话、认证用户、404 查询辅助。

原则：所有 DB 查询统一走 repositories，deps 层只做注入和轻量校验。
"""

from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.models.session import SessionLocal
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import ApplicationRepository, UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """提供请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_application_or_404(
    app_no: str,
    db: Session = Depends(get_db),
) -> "object":
    """按申请编号获取申请，不存在时返回 404。"""
    app = ApplicationRepository(db).get_by_app_no(app_no)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"申请 {app_no} 不存在",
        )
    return app


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer 令牌并返回当前登录用户。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = UserRepository(db).get_by_id(int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已停用",
        )
    return user


def require_roles(*roles: UserRole):
    """生成角色校验依赖，仅允许指定角色访问。"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前角色无权访问该功能",
            )
        return user

    return checker
