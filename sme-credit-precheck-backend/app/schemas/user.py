from pydantic import BaseModel, Field

from app.models.enums import UserRole
from app.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="有效期（秒）")
    user: UserRead = Field(description="登录用户信息")
