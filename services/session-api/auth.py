from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt


JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_MINUTES = 60 * 12


class AuthError(ValueError):
    pass


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(
    *,
    user_id: str,
    email: str,
    jwt_secret: str,
    minutes: int = DEFAULT_TOKEN_MINUTES,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, jwt_secret: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token.") from exc
    if not payload.get("sub"):
        raise AuthError("Token missing subject.")
    return payload
