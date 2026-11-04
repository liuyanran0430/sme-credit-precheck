"""MaterialRepository 测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import MaterialStatus
from app.models.material import Material
from app.models.session import SessionLocal
from app.repositories.application import ApplicationRepository
from app.repositories.material import MaterialRepository

CC = "913301001234567890"


@pytest.fixture
def app_and_repo():
    db = SessionLocal()
    app_repo = ApplicationRepository(db)
    app = app_repo.create(
        app_no=app_repo.next_app_no("AP"),
        company_name="Repo Material 测试",
        credit_code=CC,
        amount=Decimal("50"),
        product="普惠小微经营贷",
        manager_name="测试客户经理",
    )
    yield app, MaterialRepository(db)
    app_repo.delete_cascade(app)
    db.close()


class TestMaterialRepository:
    def test_list_by_app_empty_by_default(self, app_and_repo) -> None:
        app, repo = app_and_repo
        assert repo.list_by_app(app.id) == []

    def test_add_and_list(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="营业执照",
            file_name="test.pdf",
            file_url="/tmp/test.pdf",
            file_size=1024,
        )
        repo.add(m)
        repo.commit()

        listed = repo.list_by_app(app.id)
        assert len(listed) == 1
        assert listed[0].file_name == "test.pdf"

    def test_get_by_id_and_app(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="财务报表",
            file_name="t.pdf",
            file_url="/tmp/t.pdf",
            file_size=10,
        )
        repo.add(m)
        repo.commit()

        fetched = repo.get_by_id_and_app(m.id, app.id)
        assert fetched is not None
        assert fetched.file_name == "t.pdf"

    def test_get_by_id_and_app_wrong_app_returns_none(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="财务报表",
            file_name="t.pdf",
            file_url="/tmp/t.pdf",
            file_size=10,
        )
        repo.add(m)
        repo.commit()

        assert repo.get_by_id_and_app(m.id, 999999) is None

    def test_update_fields(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="营业执照",
            file_name="old.pdf",
            file_url="/tmp/old.pdf",
            file_size=10,
        )
        repo.add(m)
        repo.commit()

        updated = repo.update_fields(m, file_name="new.pdf")
        assert updated.file_name == "new.pdf"

    def test_delete(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="营业执照",
            file_name="del.pdf",
            file_url="/tmp/del.pdf",
            file_size=10,
        )
        repo.add(m)
        repo.commit()

        repo.delete(m)
        assert repo.get_by_id_and_app(m.id, app.id) is None

    def test_delete_by_app(self, app_and_repo) -> None:
        app, repo = app_and_repo
        m = Material(
            app_id=app.id,
            category="营业执照",
            file_name="x.pdf",
            file_url="/tmp/x.pdf",
            file_size=10,
        )
        repo.add(m)
        repo.commit()

        repo.delete_by_app(app.id)
        repo.commit()
        assert repo.list_by_app(app.id) == []
