"""核心安全模块单元测试：密码哈希 + JWT 签发/验签。

纯内存验证，不碰 MySQL / FastAPI / 文件系统。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest

from app.core.security import (
    TOKEN_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ====================================================================
# 密码哈希
# ====================================================================


class TestHashPassword:
    def test_hash_and_verify_roundtrip(self) -> None:
        hashed = hash_password("my-secret-password")
        assert verify_password("my-secret-password", hashed)

    def test_wrong_password_rejected(self) -> None:
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_hash_does_not_contain_plaintext(self) -> None:
        password = "super-secret-123"
        hashed = hash_password(password)
        assert password not in hashed

    def test_same_password_different_salt(self) -> None:
        """相同密码两次哈希结果不同（随机盐）。"""
        a = hash_password("same")
        b = hash_password("same")
        assert a != b

    def test_hash_format(self) -> None:
        hashed = hash_password("x")
        parts = hashed.split("$")
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1].isdigit()  # iterations
        assert len(parts[2]) == 32  # 16 字节盐 → 32 hex 字符
        assert len(parts[3]) == 64  # sha256 摘要 → 64 hex 字符

    def test_verify_malformed_hash_returns_false(self) -> None:
        assert not verify_password("x", "not-a-valid-hash")
        assert not verify_password("x", "")
        assert not verify_password("x", "pbkdf2_sha256$abc$salt$digest")  # 迭代次数非数字

    def test_verify_wrong_prefix_returns_false(self) -> None:
        hashed = hash_password("x")
        # 把前缀改成别的算法
        tampered = "scrypt" + hashed[hashed.index("$"):]
        assert not verify_password("x", tampered)


# ====================================================================
# JWT 令牌
# ====================================================================


class TestAccessToken:
    def test_create_and_decode_roundtrip(self) -> None:
        token, expires_in = create_access_token(user_id=42, username="manager", role="manager")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "manager"
        assert payload["role"] == "manager"
        assert expires_in > 0

    def test_decoded_payload_has_exp(self) -> None:
        token, _ = create_access_token(user_id=1, username="u", role="manager")
        payload = decode_access_token(token)
        assert "exp" in payload

    def test_tampered_token_rejected(self) -> None:
        token, _ = create_access_token(user_id=1, username="u", role="manager")
        tampered = token + "x"
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_wrong_secret_rejected(self) -> None:
        token, _ = create_access_token(user_id=1, username="u", role="manager")
        # 用错误的密钥解码
        with patch("app.core.security.config.AUTH_SECRET_KEY", "wrong-secret"):
            with pytest.raises(jwt.InvalidTokenError):
                decode_access_token(token)

    def test_expired_token_rejected(self) -> None:
        """通过 monkeypatch 让 exp 指向过去。"""
        from app.core import security

        original_encode = jwt.encode

        def past_exp_encode(payload, *args, **kwargs):
            payload["exp"] = payload["exp"] - timedelta(days=1)
            return original_encode(payload, *args, **kwargs)

        with patch.object(jwt, "encode", side_effect=past_exp_encode):
            token, _ = security.create_access_token(user_id=1, username="u", role="manager")

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_token_uses_hs256(self) -> None:
        token, _ = create_access_token(user_id=1, username="u", role="manager")
        header = jwt.get_unverified_header(token)
        assert header["alg"] == TOKEN_ALGORITHM
