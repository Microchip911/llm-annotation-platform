"""Authentication and JWT-handling tests.

The prototype's suite asserted only ``status_code != 401``, a bar that a 404,
422, or even a 500 clears, so it validated nothing. These tests assert exact
status codes and cover the token lifecycle: valid, expired, and tampered, plus
registration and login.
"""

from datetime import UTC, datetime, timedelta

from jose import jwt

from app.config import settings
from tests.conftest import admin_headers, auth_headers, register


def _forge_token(subject: str, expired: bool = False, tampered: bool = False) -> str:
    """Build a JWT for negative-path tests, signed with the test secret."""
    expires = datetime.now(UTC) + timedelta(minutes=-5 if expired else 5)
    token = jwt.encode(
        {"sub": subject, "exp": expires}, settings.secret_key, algorithm=settings.algorithm
    )
    return token + "tampered" if tampered else token


def test_register_returns_public_user_without_password(client):
    resp = client.post(
        "/auth/register", json={"email": "a@example.com", "password": "password123"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "a@example.com"
    assert body["role"] == "annotator"
    assert "password" not in body and "hashed_password" not in body


def test_login_issues_bearer_token(client):
    client.post("/auth/register", json={"email": "b@example.com", "password": "password123"})
    resp = client.post("/auth/token", data={"username": "b@example.com", "password": "password123"})
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_duplicate_email_is_rejected(client):
    client.post("/auth/register", json={"email": "dup@example.com", "password": "password123"})
    resp = client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )
    assert resp.status_code == 409


def test_wrong_password_is_rejected(client):
    client.post("/auth/register", json={"email": "c@example.com", "password": "password123"})
    resp = client.post("/auth/token", data={"username": "c@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_protected_route_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


def test_valid_token_grants_access(client):
    headers = auth_headers(client)
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "annotator@example.com"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_expired_token_is_rejected(client):
    # Register a REAL user so the only reason for a 401 is the expiry itself.
    user_id = register(client, email="expired@example.com").json()["id"]
    # Positive control: a fresh token for the same user is accepted...
    assert client.get("/auth/me", headers=_bearer(_forge_token(str(user_id)))).status_code == 200
    # ...so this 401 is attributable specifically to expiry, not a missing user.
    token = _forge_token(str(user_id), expired=True)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_tampered_token_is_rejected(client):
    user_id = register(client, email="tampered@example.com").json()["id"]
    assert client.get("/auth/me", headers=_bearer(_forge_token(str(user_id)))).status_code == 200
    token = _forge_token(str(user_id), tampered=True)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_for_unknown_user_is_rejected(client):
    # Well-formed, correctly signed, but the referenced user does not exist.
    token = _forge_token("999999")
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_registration_cannot_self_assign_admin(client):
    # A client trying to smuggle role=admin is silently downgraded to annotator.
    resp = client.post(
        "/auth/register",
        json={"email": "sneaky@example.com", "password": "password123", "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "annotator"


def test_users_list_is_admin_only(client):
    annotator = auth_headers(client, email="normal@example.com")
    assert client.get("/auth/users", headers=annotator).status_code == 403

    admin = admin_headers(client)
    resp = client.get("/auth/users", headers=admin)
    assert resp.status_code == 200
    assert any(user["role"] == "admin" for user in resp.json())
