"""app/qa —— 政策问答 Agent 后端实现。"""

from app.qa.intent import (
    Intent,
    RetrievalPlan,
    PRODUCT_ALIASES,
    PRODUCT_CODE_TO_NAME,
    detect_intent,
)
from app.qa.schemas import QaRequest, QaResponse, ReferenceItem, SuggestionResponse
from app.qa.service import ask_question, get_suggestions

__all__ = [
    "detect_intent",
    "ask_question",
    "get_suggestions",
    "Intent",
    "RetrievalPlan",
    "PRODUCT_ALIASES",
    "PRODUCT_CODE_TO_NAME",
    "QaRequest",
    "QaResponse",
    "ReferenceItem",
    "SuggestionResponse",
]
