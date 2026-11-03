"""pytest 共享 fixtures。

主要服务于：
1. 日志系统测试：隔离日志目录、重置全局初始化状态、清理 root logger handlers
2. API 测试：TestClient、测试账号、认证 token（manager / risk 两种角色）
3. 数据库测试：每个测试独立的 SessionLocal 会话
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.logging import LogContext
from app.core.security import hash_password
from app.main import app
from app.models.enums import UserRole
from app.models.session import SessionLocal
from app.models.user import User


# ====================================================================
# 日志隔离 fixture（原有，保留不动）
# ====================================================================


@pytest.fixture
def isolate_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import app.core.logging as logmod

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(logmod, "_LOGS_DIR", logs_dir)
    monkeypatch.setattr(logmod, "_initialized", False)

    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass
    root.setLevel(logging.NOTSET)

    for lib in ("uvicorn.access", "httpx", "uvicorn.error"):
        logging.getLogger(lib).setLevel(logging.NOTSET)

    LogContext.clear()

    yield logs_dir

    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass
    root.setLevel(logging.NOTSET)
    monkeypatch.setattr(logmod, "_initialized", False)
    LogContext.clear()


# ====================================================================
# API 测试共享 fixtures
# ====================================================================


# 统一测试账号（避免各文件各自起名造成冲突）
TEST_MANAGER = {
    "username": "test_mgr",
    "password": "test-pass-123",
    "full_name": "测试客户经理",
    "role": UserRole.MANAGER,
}
TEST_RISK = {
    "username": "test_risk",
    "password": "test-pass-456",
    "full_name": "测试风控",
    "role": UserRole.RISK,
}


@pytest.fixture
def client() -> TestClient:
    """每个测试独立的 TestClient（触发 lifespan 自动建表）。"""
    with TestClient(app) as c:
        yield c


def _create_user(user_def: dict) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == user_def["username"]))
        db.add(
            User(
                username=user_def["username"],
                full_name=user_def["full_name"],
                role=user_def["role"],
                hashed_password=hash_password(user_def["password"]),
            )
        )
        db.commit()


def _delete_user(username: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == username))
        db.commit()


@pytest.fixture
def manager_user() -> dict:
    """确保 manager 测试账号存在，测试后清理。"""
    _create_user(TEST_MANAGER)
    yield TEST_MANAGER
    _delete_user(TEST_MANAGER["username"])


@pytest.fixture
def risk_user() -> dict:
    """确保 risk 测试账号存在，测试后清理。"""
    _create_user(TEST_RISK)
    yield TEST_RISK
    _delete_user(TEST_RISK["username"])


def _login(client: TestClient, user_def: dict) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": user_def["username"], "password": user_def["password"]},
    )
    assert r.status_code == 200, f"登录失败: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture
def manager_token(client: TestClient, manager_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, manager_user)}"}


@pytest.fixture
def risk_token(client: TestClient, risk_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, risk_user)}"}


@pytest.fixture
def db_session():
    """每个测试独立的数据库会话，测试后回滚。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
