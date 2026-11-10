"""统一对话入口分流单元测试。

覆盖：
1. 个人化业务问题 → 授信助手
2. 带当前申请上下文（app_id）→ 授信助手
3. 命中申请编号 / 业务语义 → 授信助手
4. 纯政策问题 → 政策问答
5. 无关问题 → 政策问答（由其返回固定提示）
6. 只填充对应侧结果，参数正确透传

不依赖 MySQL 与真实 LLM，两个子能力全部 patch 隔离。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.assistant.schemas import AssistantResponse
from app.chat.schemas import ChatRequest
from app.chat.service import dispatch
from app.models.enums import UserRole
from app.models.user import User
from app.qa.schemas import QaMessage, QaResponse


def _user() -> User:
    return User(
        username="mgr_zhangsan",
        full_name="张三",
        role=UserRole.MANAGER,
        hashed_password="x",
        is_active=True,
    )


def _assistant_response(answer: str = "助手回答") -> AssistantResponse:
    return AssistantResponse(answer=answer, confidence=0.8, request_id="ch-test")


def _qa_response(answer: str = "政策回答") -> QaResponse:
    return QaResponse(answer=answer, confidence=0.7, request_id="ch-test")


def _run(question: str, *, app_id: int | None = None, product: str | None = None):
    db = MagicMock()
    with patch("app.chat.service.assistant_chat") as assistant_mock, patch(
        "app.chat.service.ask_question"
    ) as qa_mock:
        assistant_mock.return_value = _assistant_response()
        qa_mock.return_value = _qa_response()
        resp = dispatch(
            ChatRequest(question=question, app_id=app_id, product=product),
            _user(),
            db,
            request_id="ch-test",
        )
    return resp, assistant_mock, qa_mock


def test_personal_business_question_routes_to_assistant():
    resp, assistant_mock, qa_mock = _run("我有几笔待补件？")

    assert resp.route == "assistant"
    assert resp.assistant is not None
    assert resp.qa is None
    assistant_mock.assert_called_once()
    qa_mock.assert_not_called()


def test_app_context_routes_to_assistant():
    resp, assistant_mock, qa_mock = _run("这笔能通过吗？", app_id=12)

    assert resp.route == "assistant"
    assistant_mock.assert_called_once()
    qa_mock.assert_not_called()
    passed_req = assistant_mock.call_args.args[0]
    assert passed_req.app_id == 12


def test_application_no_routes_to_assistant():
    resp, _, qa_mock = _run("AP20260001 现在什么情况")

    assert resp.route == "assistant"
    qa_mock.assert_not_called()


def test_business_term_routes_to_assistant():
    resp, _, qa_mock = _run("这笔申请缺什么材料")

    assert resp.route == "assistant"
    qa_mock.assert_not_called()


def test_risk_review_queue_question_routes_to_assistant():
    """风控复核队列问法应路由到助手（走 list_review_queue 工具），而非政策问答。"""
    for question in (
        "当前有哪些待我复核的申请？",
        "今天有多少待复核的申请",
        "我的复核队列里有哪些单子",
    ):
        resp, assistant_mock, qa_mock = _run(question)
        assert resp.route == "assistant", f"问题未路由到助手: {question}"
        assistant_mock.assert_called_once()
        qa_mock.assert_not_called()


def test_policy_question_routes_to_qa():
    resp, assistant_mock, qa_mock = _run(
        "普惠小微经营贷的准入要求有哪些？", product="普惠小微经营贷"
    )

    assert resp.route == "qa"
    assert resp.qa is not None
    assert resp.assistant is None
    qa_mock.assert_called_once()
    assistant_mock.assert_not_called()
    passed_req = qa_mock.call_args.args[0]
    assert passed_req.product == "普惠小微经营贷"


def test_out_of_scope_question_routes_to_qa():
    resp, assistant_mock, _ = _run("今天天气怎么样")

    assert resp.route == "qa"
    assistant_mock.assert_not_called()


def test_history_is_forwarded_to_qa():
    db = MagicMock()
    history = [QaMessage(role="user", content="上一个问题")]
    with patch("app.chat.service.assistant_chat") as assistant_mock, patch(
        "app.chat.service.ask_question"
    ) as qa_mock:
        qa_mock.return_value = _qa_response()
        dispatch(
            ChatRequest(question="营业执照要什么状态？", chat_history=history),
            _user(),
            db,
            request_id="ch-test",
        )

    assistant_mock.assert_not_called()
    passed_req = qa_mock.call_args.args[0]
    assert passed_req.chat_history == history
    assert qa_mock.call_args.kwargs["request_id"] == "ch-test"
