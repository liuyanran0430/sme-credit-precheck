"""UserRepository 测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.session import SessionLocal
from app.models.user import User
from app.repositories.user import UserRepository


@pytest.fixture
def repo():
    db = SessionLocal()
    try:
        yield UserRepository(db)
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def test_user(repo):
    """创建一个测试用户，结束后清理。"""
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == "repo_test_user"))
        db.add(
            User(
                username="repo_test_user",
                full_name="Repo 测试用户",
                role=UserRole.MANAGER,
                hashed_password=hash_password("pass123"),
            )
        )
        db.commit()

    user = repo.get_by_username("repo_test_user")
    yield user

    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == "repo_test_user"))
        db.commit()


class TestUserRepository:
    def test_get_by_username_existing(self, repo, test_user) -> None:
        user = repo.get_by_username("repo_test_user")
        assert user is not None
        assert user.username == "repo_test_user"
        assert user.role == UserRole.MANAGER

    def test_get_by_username_nonexistent(self, repo) -> None:
        assert repo.get_by_username("nonexistent_user_xyz") is None

    def test_get_by_id_existing(self, repo, test_user) -> None:
        user = repo.get_by_id(test_user.id)
        assert user is not None
        assert user.username == test_user.username

    def test_get_by_id_nonexistent(self, repo) -> None:
        assert repo.get_by_id(999999) is None

    def test_password_hash_not_plaintext(self, repo, test_user) -> None:
        assert "pass123" not in test_user.hashed_password
