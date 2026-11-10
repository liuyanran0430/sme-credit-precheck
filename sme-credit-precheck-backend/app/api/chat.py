"""统一对话入口 API 路由。

POST /api/v1/chat/dispatch：一个输入框自动分流政策问答 / 授信助手。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.chat.schemas import ChatRequest, ChatResponse
from app.chat.service import dispatch
from app.core.logging import LogContext
from app.models.user import User

router = APIRouter()


@router.post("/dispatch", response_model=ChatResponse, summary="统一问答入口（自动分流）")
def chat_dispatch(
    _: Request,
    req: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    request_id = f"ch-{uuid.uuid4().hex[:10]}"
    with LogContext(request_id=request_id, user_id=user.id, user=user.username):
        return dispatch(req, user, db, request_id=request_id)
