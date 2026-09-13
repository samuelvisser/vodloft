import pytest

from backend.security import create_session_token, hash_password, verify_password, verify_session_token


def test_password_hash_round_trip() -> None:
    encoded = hash_password("a sufficiently long password")
    assert verify_password("a sufficiently long password", encoded)
    assert not verify_password("wrong password", encoded)


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="8 characters"):
        hash_password("short")


def test_session_token_is_signed_and_expires() -> None:
    token = create_session_token("admin", "secret", lifetime=60)
    assert verify_session_token(token, "admin", "secret")
    assert not verify_session_token(token, "other", "secret")
    assert not verify_session_token(token, "admin", "different-secret")
    expired = create_session_token("admin", "secret", lifetime=-1)
    assert not verify_session_token(expired, "admin", "secret")
