"""AI 解读（interpretation_text）相关测试。

覆盖：
1. generate_interpretation：LLM 成功 / 抛异常 / 返回空 三条路径
2. ReportRepository.upsert_for_app：解读写入与重新预审时覆盖
3. 报告查询接口透出 interpretation_text 字段
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.llm.base import LLMResponse
from app.repositories import ReportRepository
from app.services.precheck_summary import generate_interpretation

REPORT_LIKE = {
    "conclusion": "pass",
    "summary": "整体符合准入要求",
    "pass_rate": Decimal("85.50"),
    "rule_results": {
        "rules": [
            {"rule_id": "AP-001", "rule_name": "成立年限", "result": "pass"},
            {
                "rule_id": "AP-002",
                "rule_name": "资产负债率",
                "result": "uncertain",
                "detail": "缺少最新一期财报",
            },
        ],
        "pass_count": 8,
        "total_count": 10,
        "hard_fail_count": 0,
        "soft_fail_count": 0,
        "uncertain_count": 2,
        "level": "A",
    },
    "risk_signals": [{"level": "medium", "title": "流水波动较大"}],
    "conflicts": [],
    "completeness": {"missing": []},
}


def _mock_client(content: str | None = None, exc: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if exc is not None:
        client.chat.side_effect = exc
    else:
        client.chat.return_value = LLMResponse(content=content or "", model="test-model")
    return client


class TestGenerateInterpretation:
    def test_llm_success_returns_llm_text(self):
        client = _mock_client(content="  该申请预审通过，通过率 85.5%，建议正常推进。  ")
        with patch("app.llm.get_client", return_value=client):
            text = generate_interpretation(
                REPORT_LIKE, app_no="AP00000001", company_name="测试企业"
            )
        assert text == "该申请预审通过，通过率 85.5%，建议正常推进。"
        # prompt 中应包含快照关键信息（仅转述，不重新判定）
        user_prompt = client.chat.call_args.kwargs["user"]
        assert "AP00000001" in user_prompt
        assert "85.5%" in user_prompt
        assert "资产负债率" in user_prompt

    def test_llm_exception_falls_back_to_template(self):
        client = _mock_client(exc=RuntimeError("LLM 服务不可用"))
        with patch("app.llm.get_client", return_value=client):
            text = generate_interpretation(
                REPORT_LIKE, app_no="AP00000001", company_name="测试企业"
            )
        # 降级为模板文本，不抛异常
        assert text.startswith("申请 AP00000001（测试企业）AI 预审摘要：")
        assert "预审结论：符合" in text
        assert "85.5%" in text

    def test_llm_empty_content_falls_back_to_template(self):
        client = _mock_client(content="   ")
        with patch("app.llm.get_client", return_value=client):
            text = generate_interpretation(
                REPORT_LIKE, app_no="AP00000001", company_name="测试企业"
            )
        assert text.startswith("申请 AP00000001（测试企业）AI 预审摘要：")

    def test_llm_overlong_text_truncated(self):
        client = _mock_client(content="x" * 1000)
        with patch("app.llm.get_client", return_value=client):
            text = generate_interpretation(
                REPORT_LIKE, app_no="AP00000001", company_name="测试企业"
            )
        assert len(text) == 600


class TestUpsertInterpretation:
    """upsert_for_app 写入与覆盖 interpretation_text，并通过报告接口透出。"""

    def _upsert(self, db, app_id: int, interpretation: str | None):
        return ReportRepository(db).upsert_for_app(
            app_id,
            conclusion="pass",
            summary="摘要",
            pass_rate=Decimal("80.00"),
            completeness={},
            consistency={},
            rule_results={},
            risk_signals=[],
            conflicts=[],
            rule_version="v1",
            rule_snapshot=None,
            interpretation_text=interpretation,
        )

    def test_write_overwrite_and_api_expose(
        self, client, manager_token, db_session
    ) -> None:
        # 通过 API 创建申请（报告外键依赖）
        r = client.post(
            "/api/v1/applications",
            json={
                "company_name": "解读测试企业",
                "credit_code": "91330200TEST000001",
                "product": "普惠小微经营贷",
                "amount": 100,
            },
            headers=manager_token,
        )
        assert r.status_code in (200, 201), r.text
        app_no = r.json()["app_no"]

        try:
            # 查 app_id
            detail = client.get(f"/api/v1/applications/{app_no}", headers=manager_token)
            assert detail.status_code == 200, detail.text
            app_id = detail.json()["id"]

            # 首次写入
            report = self._upsert(db_session, app_id, "第一版解读")
            db_session.flush()
            assert report.interpretation_text == "第一版解读"

            # 重新预审覆盖
            report2 = self._upsert(db_session, app_id, "第二版解读")
            db_session.flush()
            assert report2.id == report.id
            assert report2.interpretation_text == "第二版解读"
            db_session.commit()

            # 报告接口透出
            resp = client.get(
                f"/api/v1/applications/{app_no}/report", headers=manager_token
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["interpretation_text"] == "第二版解读"
        finally:
            client.delete(f"/api/v1/applications/{app_no}", headers=manager_token)
