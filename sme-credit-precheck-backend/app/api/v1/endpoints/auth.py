from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.user import LoginRequest, TokenResponse, UserRead

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="用户登录",
    description="校验用户名密码，成功返回 JWT 访问令牌与用户信息。",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已停用，请联系管理员",
        )

    token, expires_in = create_access_token(user.id, user.username, user.role.value)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="获取当前登录用户",
    description="根据访问令牌返回当前用户信息，用于前端恢复登录态与角色校验。",
)
def read_me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
