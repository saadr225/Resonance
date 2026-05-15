from __future__ import annotations

from typing import Any

import jwt


JWT_ALGORITHM = "HS256"


class AuthError(ValueError):
    pass


def decode_access_token(token: str, jwt_secret: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token.") from exc
    if not payload.get("sub"):
        raise AuthError("Token missing subject.")
    return payload
