"""Pydantic Schema 边界值校验测试。

验证请求体的字段约束（长度、正则、数值范围、model_validator）。
纯内存，不碰数据库。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ApplicationStatus
from app.schemas.application import ApplicationCreate, ApplicationEdit, ApplicationUpdate


VALID_CC = "913301001234567890"  # 18 位大写字母数字


class TestApplicationCreate:
    def test_valid_input_ok(self) -> None:
        obj = ApplicationCreate(
            company_name="测试企业",
            credit_code=VALID_CC,
            amount=50.0,
            product="普惠小微经营贷",
        )
        assert obj.credit_code == VALID_CC

    @pytest.mark.parametrize(
        "bad_cc",
        [
            "",                          # 空
            "123",                       # 太短
            "9133010012345678901",       # 19 位太长
            "91330100123456789a",        # 小写字母
            "91-330100123456789",        # 含特殊字符
            "!@#$%^&*()_+-=[]{}",        # 全特殊字符
        ],
    )
    def test_invalid_credit_code_rejected(self, bad_cc: str) -> None:
        with pytest.raises(ValidationError):
            ApplicationCreate(
                company_name="x",
                credit_code=bad_cc,
                amount=50.0,
                product="普惠小微经营贷",
            )

    @pytest.mark.parametrize("bad_amount", [0, -1, -0.01, -100])
    def test_non_positive_amount_rejected(self, bad_amount: float) -> None:
        with pytest.raises(ValidationError):
            ApplicationCreate(
                company_name="x",
                credit_code=VALID_CC,
                amount=bad_amount,
                product="普惠小微经营贷",
            )

    def test_missing_required_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApplicationCreate()  # 全部缺失

    def test_company_name_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApplicationCreate(
                company_name="a" * 201,
                credit_code=VALID_CC,
                amount=10,
                product="x",
            )


class TestApplicationUpdate:
    def test_valid_status_transition(self) -> None:
        obj = ApplicationUpdate(status=ApplicationStatus.SUPPLEMENT, remark="补充材料")
        assert obj.status == ApplicationStatus.SUPPLEMENT
        assert obj.remark == "补充材料"

    def test_remark_optional(self) -> None:
        obj = ApplicationUpdate(status=ApplicationStatus.RISK)
        assert obj.remark is None

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApplicationUpdate(status="not-a-valid-status")  # type: ignore[arg-type]


class TestApplicationEdit:
    def test_must_modify_at_least_one_field(self) -> None:
        with pytest.raises(ValidationError, match="至少需要修改一项"):
            ApplicationEdit()  # 全 None

    def test_blank_string_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="不能为空"):
            ApplicationEdit(company_name="   ")

    def test_single_field_accepted(self) -> None:
        obj = ApplicationEdit(company_name="新企业名")
        assert obj.company_name == "新企业名"
        assert obj.credit_code is None

    def test_invalid_credit_code_in_edit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApplicationEdit(credit_code="not-18-char")
