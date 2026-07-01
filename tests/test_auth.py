import pytest
from fastapi.testclient import TestClient
from main import app
from jose import jwt
from auth import SECRET_KEY, ALGORITHM
from datetime import datetime, timedelta

client = TestClient(app)

def make_token(expired=False, tampered=False):
    payload = {"sub": "user1"}
    if expired:
        payload["exp"] = datetime.utcnow() - timedelta(minutes=5)
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    if tampered:
        token = token + "tampered"
    return token

def test_valid_token():
    token = make_token()
    response = client.get("/annotations/1", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code != 401

def test_expired_token():
    token = make_token(expired=True)
    response = client.get("/annotations/1", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

def test_tampered_token():
    token = make_token(tampered=True)
    response = client.get("/annotations/1", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401