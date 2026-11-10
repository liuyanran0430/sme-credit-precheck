"""政策问答 API 路由（阶段 A 后端）。

两个接口：
- POST /api/v1/qa/ask          单轮问答（可带最近对话）
- GET  /api/v1/qa/suggestions  推荐问题气泡

两者均需登录态，两种角色都可访问。问答本身只读知识库，不读取任何申请/材料/报告数据。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user
from app.core import config
from app.models.user import User
from app.qa.schemas import QaRequest, QaResponse, SuggestionResponse
from app.qa.service import ask_question, get_suggestions

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/ask", response_model=QaResponse, summary="政策问答（单轮）")
def qa_ask(_: Request, req: QaRequest) -> QaResponse:
    request_id = uuid.uuid4().hex[:12]
    return ask_question(req, request_id=request_id)


@router.get("/suggestions", response_model=SuggestionResponse, summary="推荐问题气泡")
def qa_suggestions(_: Request, user: User = Depends(get_current_user)) -> SuggestionResponse:
    if not config.QA_ENABLED:
        return SuggestionResponse(questions=[])
    # 风控角色偏风险判断，客户经理偏流程与材料准备
    return get_suggestions(role=user.role.value)
