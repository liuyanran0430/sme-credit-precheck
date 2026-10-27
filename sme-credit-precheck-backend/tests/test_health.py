import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.enums import UserRole
from app.models.user import User

TEST_USERNAME = "pytest_manager"
TEST_PASSWORD = "pytest-pass-123"


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 使用上下文管理器以触发 lifespan（开发环境自动建表）
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def auth_headers(client: TestClient) -> dict[str, str]:
    """创建临时客户经理账号并登录，测试结束后清理。"""
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == TEST_USERNAME))
        db.add(
            User(
                username=TEST_USERNAME,
                full_name="测试客户经理",
                role=UserRole.MANAGER,
                hashed_password=hash_password(TEST_PASSWORD),
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    yield {"Authorization": f"Bearer {token}"}

    with SessionLocal() as db:
        db.execute(delete(User).where(User.username == TEST_USERNAME))
        db.commit()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "小微企业授信智能预审系统"


def test_login_rejects_wrong_password(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_application_list_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/applications")
    assert response.status_code == 401


def test_application_list(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/applications", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["total"], int)
    assert isinstance(body["items"], list)
    assert len(body["items"]) <= body["page_size"]


def test_current_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == TEST_USERNAME
    assert body["role"] == UserRole.MANAGER.value


def test_risk_queue_forbidden_for_manager(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/risk/queue", headers=auth_headers)
    assert response.status_code == 403
