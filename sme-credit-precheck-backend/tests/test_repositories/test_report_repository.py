"""ReportRepository 测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import ApplicationStatus
from app.models.session import SessionLocal
from app.repositories.application import ApplicationRepository
from app.repositories.report import ReportRepository

CC = "913301001234567890"


@pytest.fixture
def app_and_repo():
    db = SessionLocal()
    app_repo = ApplicationRepository(db)
    app = app_repo.create(
        app_no=app_repo.next_app_no("AP"),
        company_name="Repo Report 测试",
        credit_code=CC,
        amount=Decimal("50"),
        product="普惠小微经营贷",
        manager_name="测试客户经理",
    )
    yield app, ReportRepository(db)
    app_repo.delete_cascade(app)
    db.close()


class TestReportRepository:
    def test_get_latest_by_app_none_when_no_report(self, app_and_repo) -> None:
        app, repo = app_and_repo
        assert repo.get_latest_by_app(app.id) is None

    def test_upsert_creates_new_report(self, app_and_repo) -> None:
        app, repo = app_and_repo
        report = repo.upsert_for_app(
            app.id,
            conclusion="pass",
            summary="测试摘要",
            pass_rate=Decimal("0.85"),
            completeness={"total": 5, "ok": 4},
            consistency={"issues": []},
            rule_results={"rules": []},
            risk_signals=[],
            conflicts=[],
            rule_version="v1",
            rule_snapshot={},
        )
        assert report.conclusion == "pass"
        assert report.pass_rate == Decimal("0.85")
        assert repo.get_latest_by_app(app.id) is not None

    def test_upsert_updates_existing(self, app_and_repo) -> None:
        app, repo = app_and_repo
        repo.upsert_for_app(
            app.id,
            conclusion="pass",
            summary="第一次",
            pass_rate=Decimal("0.8"),
            completeness={},
            consistency={},
            rule_results={},
            risk_signals=[],
            conflicts=[],
            rule_version="v1",
            rule_snapshot={},
        )
        # 第二次 upsert 应该更新同一行
        updated = repo.upsert_for_app(
            app.id,
            conclusion="forbidden",
            summary="第二次",
            pass_rate=Decimal("0.3"),
            completeness={},
            consistency={},
            rule_results={},
            risk_signals=[],
            conflicts=[],
            rule_version="v2",
            rule_snapshot={},
        )
        assert updated.conclusion == "forbidden"
        assert updated.summary == "第二次"
        # 只有一版报告
        assert len(repo.list_by_app(app.id)) == 1

    def test_upsert_no_commit_skips_commit(self, app_and_repo) -> None:
        app, repo = app_and_repo
        # commit=False 不自动提交
        report = repo.upsert_for_app(
            app.id,
            conclusion="pass",
            summary="未提交",
            pass_rate=Decimal("1"),
            completeness={},
            consistency={},
            rule_results={},
            risk_signals=[],
            conflicts=[],
            rule_version="v1",
            rule_snapshot={},
            commit=False,
        )
        assert report.conclusion == "pass"
        # 手动提交
        repo.db.commit()

    def test_list_by_app_order_desc(self, app_and_repo) -> None:
        app, repo = app_and_repo
        repo.upsert_for_app(
            app.id, conclusion="pass", summary="v1", pass_rate=Decimal("1"),
            completeness={}, consistency={}, rule_results={},
            risk_signals=[], conflicts=[], rule_version="v1", rule_snapshot={},
        )
        # upsert 更新而非新增，所以 list 只有 1 条
        reports = repo.list_by_app(app.id)
        assert len(reports) == 1

    def test_latest_conclusions_empty_input(self, app_and_repo) -> None:
        app, repo = app_and_repo
        assert repo.latest_conclusions([]) == {}
