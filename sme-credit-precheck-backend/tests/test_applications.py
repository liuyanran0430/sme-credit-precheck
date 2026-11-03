"""申请管理 API CRUD 测试。

复用 conftest.py 的 client + manager_token fixtures。
覆盖：创建 / 详情 / 编辑 / 删除 / 状态流转（501） / 列表筛选 / 权限。
"""

from __future__ import annotations

import pytest

VALID_CC = "913301001234567890"


def _create_app_payload(**overrides) -> dict:
    base = {
        "company_name": "API 测试企业",
        "credit_code": VALID_CC,
        "amount": 50.0,
        "product": "普惠小微经营贷",
    }
    base.update(overrides)
    return base


class TestApplicationsAPI:
    def test_create_application_success(self, client, manager_token) -> None:
        r = client.post("/api/v1/applications", json=_create_app_payload(), headers=manager_token)
        assert r.status_code == 201
        data = r.json()
        assert data["app_no"].startswith("AP")
        assert data["company_name"] == "API 测试企业"
        assert data["credit_code"] == VALID_CC
        assert data["amount"] == 50.0
        assert data["status"] == "check"
        # 清理
        client.delete(f"/api/v1/applications/{data['app_no']}", headers=manager_token)

    def test_create_unsupported_product_400(self, client, manager_token) -> None:
        r = client.post(
            "/api/v1/applications",
            json=_create_app_payload(product="不存在的贷款"),
            headers=manager_token,
        )
        assert r.status_code == 400
        assert "不支持的贷款类型" in r.json()["detail"]

    def test_create_requires_auth(self, client) -> None:
        r = client.post("/api/v1/applications", json=_create_app_payload())
        assert r.status_code in (401, 403)

    def test_get_application_detail(self, client, manager_token) -> None:
        # 先创建
        create_r = client.post("/api/v1/applications", json=_create_app_payload(), headers=manager_token)
        app_no = create_r.json()["app_no"]

        r = client.get(f"/api/v1/applications/{app_no}", headers=manager_token)
        assert r.status_code == 200
        assert r.json()["app_no"] == app_no

        client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_get_nonexistent_application_404(self, client, manager_token) -> None:
        r = client.get("/api/v1/applications/AP00000000", headers=manager_token)
        assert r.status_code == 404

    def test_edit_application(self, client, manager_token) -> None:
        create_r = client.post(
            "/api/v1/applications",
            json=_create_app_payload(company_name="编辑前"),
            headers=manager_token,
        )
        app_no = create_r.json()["app_no"]

        r = client.patch(
            f"/api/v1/applications/{app_no}",
            json={"company_name": "编辑后"},
            headers=manager_token,
        )
        assert r.status_code == 200
        assert r.json()["company_name"] == "编辑后"

        client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_edit_credit_code_invalid(self, client, manager_token) -> None:
        create_r = client.post(
            "/api/v1/applications",
            json=_create_app_payload(),
            headers=manager_token,
        )
        app_no = create_r.json()["app_no"]

        r = client.patch(
            f"/api/v1/applications/{app_no}",
            json={"credit_code": "invalid"},
            headers=manager_token,
        )
        assert r.status_code == 422  # pydantic 校验失败

        client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_delete_application(self, client, manager_token) -> None:
        create_r = client.post("/api/v1/applications", json=_create_app_payload(), headers=manager_token)
        app_no = create_r.json()["app_no"]

        r = client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)
        assert r.status_code == 204

        # 再查应该 404
        r2 = client.get(f"/api/v1/applications/{app_no}", headers=manager_token)
        assert r2.status_code == 404

    def test_update_status_not_implemented_501(self, client, manager_token) -> None:
        create_r = client.post("/api/v1/applications", json=_create_app_payload(), headers=manager_token)
        app_no = create_r.json()["app_no"]

        r = client.patch(
            f"/api/v1/applications/{app_no}/status",
            json={"status": "manual", "remark": "待人工"},
            headers=manager_token,
        )
        assert r.status_code == 501

        client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_list_filter_by_keyword(self, client, manager_token) -> None:
        create_r = client.post(
            "/api/v1/applications",
            json=_create_app_payload(company_name="唯一关键词企业XYZ"),
            headers=manager_token,
        )
        app_no = create_r.json()["app_no"]

        r = client.get("/api/v1/applications", params={"keyword": "唯一关键词企业XYZ"}, headers=manager_token)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert any(item["app_no"] == app_no for item in data["items"])

        client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_list_with_status_filter(self, client, manager_token) -> None:
        # 新建的申请状态是 check
        r = client.get("/api/v1/applications", params={"status": "check"}, headers=manager_token)
        assert r.status_code == 200
        data = r.json()
        assert all(item["status"] == "check" for item in data["items"])
