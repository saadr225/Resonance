from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from auth import AuthError, decode_access_token


def test_decode_access_token_requires_subject() -> None:
    token = jwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=5)},
        "secret",
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        decode_access_token(token, "secret")


def test_decode_access_token_accepts_valid_token() -> None:
    token = jwt.encode(
        {"sub": "u1", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "secret",
        algorithm="HS256",
    )

    assert decode_access_token(token, "secret")["sub"] == "u1"
