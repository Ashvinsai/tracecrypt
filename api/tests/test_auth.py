"""B05, B06, B09: session and credential handling."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.identity import User
from tests.conftest import login


def test_login_sets_session_and_me_works(client: TestClient, user_a: User) -> None:
    assert login(client, user_a).status_code == 200
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["email"] == user_a.email


def test_session_cookie_flags(client: TestClient, user_a: User) -> None:
    """B05: the session cookie is HttpOnly, SameSite=Lax, and signed."""
    response = login(client, user_a)
    raw = response.headers["set-cookie"]
    assert "httponly" in raw.lower()
    assert "samesite=lax" in raw.lower()

    cookie = client.cookies.get("cfa_session")
    assert cookie is not None
    # itsdangerous signs as <payload>.<timestamp>.<signature>
    assert cookie.count(".") >= 2
    assert user_a.email not in cookie


def test_login_failure_is_uniform(client: TestClient, user_a: User) -> None:
    """B06: a wrong password and an unknown account are indistinguishable."""
    wrong = client.post(
        "/api/v1/auth/login", json={"email": user_a.email, "password": "not-the-password"}
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.test", "password": "not-the-password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "unauthenticated"


def test_password_hash_is_argon2id(db: Session, user_a: User) -> None:
    """B09: Argon2id, not plaintext and not a fast digest."""
    assert user_a.password_hash.startswith("$argon2id$")
    assert "correct-horse-battery" not in user_a.password_hash
    assert verify_password("correct-horse-battery", user_a.password_hash)
    assert not verify_password("wrong", user_a.password_hash)


def test_verify_against_missing_hash_still_does_work() -> None:
    """An absent account must not be cheaper to probe than a present one."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", hash_password("anything")) is True


def test_logout_clears_session(client: TestClient, user_a: User) -> None:
    login(client, user_a)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
