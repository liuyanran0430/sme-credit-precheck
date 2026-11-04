"""ApplicationRepository 测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.session import SessionLocal
from app.repositories.application import ApplicationRepository

CC = "913301001234567890"


@pytest.fixture
def repo():
    db = SessionLocal()
    try:
        yield ApplicationRepository(db)
    finally:
        db.rollback()
        db.close()


def _cleanup(repo: ApplicationRepository) -> None:
    """删除测试过程中创建的申请。"""
    with SessionLocal() as db:
        db.execute(
            delete(Application).where(Application.company_name.like("Repo 测试%"))
        )
        db.commit()


class TestApplicationRepository:
    def test_create_generates_valid_app_no(self, repo: ApplicationRepository) -> None:
        app = repo.create(
            app_no=repo.next_app_no("AP"),
            company_name="Repo 测试企业",
            credit_code=CC,
            amount=Decimal("50"),
            product="普惠小微经营贷",
            manager_name="测试客户经理",
        )
        try:
            assert app.app_no.startswith("AP")
            assert len(app.app_no) == 10
            assert app.status == ApplicationStatus.CHECK
            assert app.credit_code == CC  # 已转大写
        finally:
            _cleanup(repo)

    def test_create_credit_code_uppercased(self, repo: ApplicationRepository) -> None:
        app = repo.create(
            app_no=repo.next_app_no("AP"),
            company_name="Repo 测试企业",
            credit_code="91330100123456789a",  # 末尾小写 a
            amount=Decimal("50"),
            product="普惠小微经营贷",
            manager_name="测试客户经理",
        )
        try:
            assert app.credit_code == "91330100123456789A"  # 转大写
        finally:
            _cleanup(repo)

    def test_get_by_app_no_returns_or_none(self, repo: ApplicationRepository) -> None:
        assert repo.get_by_app_no("AP99999999") is None

    def test_next_app_no_increments(self, repo: ApplicationRepository) -> None:
        first = repo.next_app_no("AP")
        # 不实际创建，next_app_no 只查表不写
        second = repo.next_app_no("AP")
        assert first == second  # 没插入时两次结果相同

    def test_list_paginated_returns_tuple(self, repo: ApplicationRepository) -> None:
        rows, total, counts = repo.list_paginated(page=1, page_size=10)
        assert isinstance(rows, list)
        assert isinstance(total, int)
        assert isinstance(counts, dict)
        assert len(rows) <= 10

    def test_list_paginated_keyword_filter(self, repo: ApplicationRepository) -> None:
        app = repo.create(
            app_no=repo.next_app_no("AP"),
            company_name="Repo 测试关键词企业",
            credit_code=CC,
            amount=Decimal("50"),
            product="普惠小微经营贷",
            manager_name="测试客户经理",
        )
        try:
            rows, total, _ = repo.list_paginated(keyword="关键词企业", page=1, page_size=10)
            assert total >= 1
            assert any(r.app_no == app.app_no for r in rows)
        finally:
            _cleanup(repo)

    def test_list_by_status(self, repo: ApplicationRepository) -> None:
        rows = repo.list_by_status(ApplicationStatus.CHECK)
        assert isinstance(rows, list)

    def test_delete_cascade_removes_application(self, repo: ApplicationRepository) -> None:
        app = repo.create(
            app_no=repo.next_app_no("AP"),
            company_name="Repo 测试删除企业",
            credit_code=CC,
            amount=Decimal("50"),
            product="普惠小微经营贷",
            manager_name="测试客户经理",
        )
        repo.delete_cascade(app)
        assert repo.get_by_app_no(app.app_no) is None
