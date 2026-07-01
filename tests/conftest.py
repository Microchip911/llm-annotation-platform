"""Shared pytest fixtures.

Tests run against the real application stack, but pointed at a throwaway SQLite
database in the OS temp directory and given a fixed, ephemeral signing secret.
The environment is configured *before* the app is imported (settings are read at
import time), and every test gets a freshly created / torn-down schema so tests
are fully isolated from one another and from your local ``app.db``.
"""

import os
import tempfile

# --- Must run before any `app.*` import so settings pick these up -----------
# We *force* these (not setdefault): if the surrounding shell/CI already exported
# DATABASE_URL, deferring to it would run — and drop_all — against a real
# database while still looking green. The test DB must be non-negotiable.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
_TEST_DATABASE_URL = f"sqlite:///{_tmp_db.name}"
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-only-secret-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401  (register models on Base.metadata)
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Belt-and-suspenders: fail loudly if anything ever routes tests at a real DB.
assert settings.database_url == _TEST_DATABASE_URL, (
    f"tests must run against the temp DB, not {settings.database_url!r}"
)


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Create all tables before each test and drop them afterwards."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    """A TestClient bound to the app for the duration of a test."""
    with TestClient(app) as test_client:
        yield test_client


# --- Small helpers shared across test modules -------------------------------
def register(client, email="annotator@example.com", password="password123"):
    """Register an annotator via the public API; returns the raw response."""
    return client.post("/auth/register", json={"email": email, "password": password})


def _login(client, email, password):
    token = client.post(
        "/auth/token", data={"username": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def auth_headers(client, email="annotator@example.com", password="password123"):
    """Register (idempotently) and log in as an annotator; returns an auth header."""
    register(client, email=email, password=password)
    return _login(client, email, password)


def seed_user(email, password, role=models.Role.ANNOTATOR):
    """Create a user directly in the DB — the trusted path for provisioning admins.

    Admins are intentionally *not* creatable through the public API, so tests
    that need one insert it here rather than self-registering as admin.
    """
    db = SessionLocal()
    try:
        from app.security import hash_password

        user = models.User(
            email=email, hashed_password=hash_password(password), role=role.value
        )
        db.add(user)
        db.commit()
    finally:
        db.close()


def admin_headers(client, email="admin@example.com", password="password123"):
    """Provision an admin out-of-band, then log in; returns an auth header."""
    seed_user(email, password, role=models.Role.ADMIN)
    return _login(client, email, password)
