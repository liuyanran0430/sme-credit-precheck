"""风控复核决策 API 测试。

覆盖：提交风控决策时持久化逐项风险复核结果（checklist_result）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.session import SessionLocal

VALID_CC = "913301001234567890"


def _create_app(client, manager_token) -> str:
    r = client.post(
        "/api/v1/applications",
        json={
            "company_name": "风控逐项复核测试企业",
            "credit_code": VALID_CC,
            "amount": 80.0,
            "product": "普惠小微经营贷",
        },
        headers=manager_token,
    )
    assert r.status_code == 201, r.text
    return r.json()["app_no"]


def _set_status(app_no: str, status: ApplicationStatus) -> None:
    with SessionLocal() as db:
        app = db.scalar(select(Application).where(Application.app_no == app_no))
        assert app is not None
        app.status = status
        db.commit()


class TestRiskDecisionItems:
    def test_submit_with_items_persists_checklist(
        self, client, manager_token, risk_token
    ) -> None:
        app_no = _create_app(client, manager_token)
        try:
            _set_status(app_no, ApplicationStatus.RISK)
            items = [
                {
                    "signal_id": "RS-001",
                    "title": "征信授权书有效期不足",
                    "action": "confirm",
                    "comment": "已核实，确需重签",
                },
                {
                    "signal_id": "RS-002",
                    "title": "企业名称一致性",
                    "action": "exclude",
                    "comment": None,
                },
            ]
            r = client.post(
                f"/api/v1/risk/{app_no}/decision",
                json={"decision": "reject", "opinion": "材料需补充说明", "items": items},
                headers=risk_token,
            )
            assert r.status_code == 201, r.text
            data = r.json()
            assert data["checklist_result"] is not None
            assert len(data["checklist_result"]) == 2
            assert data["checklist_result"][0]["signal_id"] == "RS-001"
            assert data["checklist_result"][0]["action"] == "confirm"
            assert data["checklist_result"][1]["action"] == "exclude"

            # 复核记录查询接口同样返回逐项结果
            r2 = client.get(f"/api/v1/risk/{app_no}/reviews", headers=manager_token)
            assert r2.status_code == 200
            reviews = r2.json()
            assert reviews[0]["checklist_result"][0]["title"] == "征信授权书有效期不足"
        finally:
            client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_submit_without_items_checklist_none(
        self, client, manager_token, risk_token
    ) -> None:
        app_no = _create_app(client, manager_token)
        try:
            _set_status(app_no, ApplicationStatus.RISK)
            r = client.post(
                f"/api/v1/risk/{app_no}/decision",
                json={"decision": "pass", "opinion": "无风险信号，同意通过"},
                headers=risk_token,
            )
            assert r.status_code == 201, r.text
            assert r.json()["checklist_result"] is None
        finally:
            client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)

    def test_invalid_item_action_422(self, client, manager_token, risk_token) -> None:
        app_no = _create_app(client, manager_token)
        try:
            _set_status(app_no, ApplicationStatus.RISK)
            r = client.post(
                f"/api/v1/risk/{app_no}/decision",
                json={
                    "decision": "pass",
                    "opinion": "测试",
                    "items": [{"signal_id": "RS-1", "title": "t", "action": "bad"}],
                },
                headers=risk_token,
            )
            assert r.status_code == 422
        finally:
            client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)
