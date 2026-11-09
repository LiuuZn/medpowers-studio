from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from .config import get_settings

API_TOKEN_PREFIX = "mps_"
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> tuple[str, int]:
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "exp": now + expires_delta,
        "iat": now,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def hash_api_token(raw_token: str) -> str:
    """API token 具有 256 位随机熵，使用 SHA-256 摘要即可安全落库。"""

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    """返回 (明文, 展示前缀, 摘要)。明文只在创建时返回一次。"""

    raw = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, raw[:12], hash_api_token(raw)


def generate_device_code() -> str:
    return secrets.token_urlsafe(32)


def generate_user_code() -> str:
    chars = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def normalize_user_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def hash_user_code(code: str) -> str:
    return hashlib.sha256(normalize_user_code(code).encode("utf-8")).hexdigest()
