"""ReviewRepository 测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.review import ManualReview, RiskReview
from app.models.session import SessionLocal
from app.repositories.application import ApplicationRepository
from app.repositories.review import ReviewRepository

CC = "913301001234567890"


@pytest.fixture
def app_and_repo():
    db = SessionLocal()
    app_repo = ApplicationRepository(db)
    app = app_repo.create(
        app_no=app_repo.next_app_no("AP"),
        company_name="Repo Review 测试",
        credit_code=CC,
        amount=Decimal("50"),
        product="普惠小微经营贷",
        manager_name="测试客户经理",
    )
    yield app, ReviewRepository(db)
    app_repo.delete_cascade(app)
    db.close()


class TestReviewRepository:
    def test_list_manual_by_app_empty(self, app_and_repo) -> None:
        app, repo = app_and_repo
        assert repo.list_manual_by_app(app.id) == []

    def test_create_manual_review(self, app_and_repo) -> None:
        app, repo = app_and_repo
        review = repo.create_manual(
            ManualReview(
                app_id=app.id,
                reviewer="manager",
                decision=ReviewDecision.PASS,
                checklist_result=[{"item_id": 1, "action": "确认通过"}],
                comment=None,
            )
        )
        assert review.id is not None
        assert review.decision == ReviewDecision.PASS
        assert len(repo.list_manual_by_app(app.id)) == 1

    def test_list_risk_by_app_empty(self, app_and_repo) -> None:
        app, repo = app_and_repo
        assert repo.list_risk_by_app(app.id) == []

    def test_create_risk_review(self, app_and_repo) -> None:
        app, repo = app_and_repo
        review = repo.create_risk(
            RiskReview(
                app_id=app.id,
                reviewer="risk",
                decision=ReviewDecision.REJECT,
                opinion="需补充材料",
            )
        )
        assert review.id is not None
        assert review.decision == ReviewDecision.REJECT
        assert len(repo.list_risk_by_app(app.id)) == 1

    def test_risk_returned_app_ids(self, app_and_repo) -> None:
        app, repo = app_and_repo
        # 没风控退回记录时集合为空或不含当前 app
        returned = repo.risk_returned_app_ids()
        assert app.id not in returned

        # 创建一条退回记录
        repo.create_risk(
            RiskReview(
                app_id=app.id,
                reviewer="risk",
                decision=ReviewDecision.REJECT,
                opinion="退回",
            )
        )
        returned = repo.risk_returned_app_ids()
        assert app.id in returned

    def test_list_risk_queue(self, app_and_repo) -> None:
        app, repo = app_and_repo
        # 默认状态是 CHECK，不在风险队列
        queue = repo.list_risk_queue()
        assert all(a.status == ApplicationStatus.RISK for a in queue)
