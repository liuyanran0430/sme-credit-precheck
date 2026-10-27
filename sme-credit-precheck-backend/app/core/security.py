"""密码哈希与访问令牌签发（PBKDF2 + PyJWT）。"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.core import config

_HASH_PREFIX = "pbkdf2_sha256"
_HASH_ITERATIONS = 260000
TOKEN_ALGORITHM = "HS256"


def _derive(password: str, salt: str, iterations: int = _HASH_ITERATIONS) -> str:
    """按 PBKDF2-HMAC-SHA256 派生密码摘要。"""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()


def hash_password(password: str) -> str:
    """生成带随机盐的密码哈希，格式：算法$迭代次数$盐$摘要。"""
    salt = os.urandom(16).hex()
    return f"{_HASH_PREFIX}${_HASH_ITERATIONS}${salt}${_derive(password, salt)}"


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配（常数时间比较）。"""
    try:
        prefix, iterations, salt, digest = hashed.split("$")
        if prefix != _HASH_PREFIX:
            return False
        expected = _derive(password, salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, digest)


def create_access_token(user_id: int, username: str, role: str) -> tuple[str, int]:
    """签发访问令牌，返回（令牌, 有效期秒数）。"""
    expires_in = config.AUTH_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, config.AUTH_SECRET_KEY, algorithm=TOKEN_ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """解析并校验访问令牌，失败时抛出 jwt 异常。"""
    return jwt.decode(token, config.AUTH_SECRET_KEY, algorithms=[TOKEN_ALGORITHM])
