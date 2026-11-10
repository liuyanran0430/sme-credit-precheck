"""授信助手 API 路由。

POST /api/v1/assistant/chat 单轮对话：只读本人名下业务数据，不提供任何写操作。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.assistant.agent import AgentType, chat
from app.assistant.schemas import AssistantRequest, AssistantResponse
from app.core.logging import LogContext
from app.models.enums import UserRole
from app.models.user import User

router = APIRouter()


@router.post("/chat", response_model=AssistantResponse, summary="授信助手（单轮）")
def assistant_chat(
    _: Request,
    req: AssistantRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AssistantResponse:
    request_id = f"as-{uuid.uuid4().hex[:10]}"
    agent_type: AgentType = "risk" if user.role == UserRole.RISK else "manager"
    with LogContext(request_id=request_id, user_id=user.id, user=user.username):
        return chat(req, user, db, agent_type=agent_type, request_id=request_id)
