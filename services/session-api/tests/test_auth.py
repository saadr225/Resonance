from __future__ import annotations

import pytest

from auth import AuthError, create_access_token, decode_access_token, hash_password, verify_password


def test_hash_and_verify_password() -> None:
    password_hash = hash_password("correct-horse")

    assert password_hash != "correct-horse"
    assert verify_password("correct-horse", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_short_password_rejected() -> None:
    with pytest.raises(AuthError):
        hash_password("short")


def test_jwt_round_trip() -> None:
    token = create_access_token(user_id="user-1", email="a@example.com", jwt_secret="secret")
    payload = decode_access_token(token, "secret")

    assert payload["sub"] == "user-1"
    assert payload["email"] == "a@example.com"
