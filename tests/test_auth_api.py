"""api/auth_api.py API 레이어 테스트 (TestClient).

서비스 예외 → HTTP 상태 매핑(v18에서 추가한 429/400 등)을 검증한다.
api/__init__을 비워 둔 덕에 auth 라우터만 가볍게 올릴 수 있다(torch 미로드).

전화번호는 서비스 테스트(0109999)와 겹치지 않게 0108888 대역을 쓴다.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_api import router
from database import get_db


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    # get_db를 savepoint 세션으로 오버라이드 — 테스트 종료 시 롤백된다.
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_request_code_returns_dev_code(client):
    r = client.post("/api/auth/signup/request-code", json={"phone_number": "01088880001"})
    assert r.status_code == 200
    assert r.json()["dev_code"] is not None


def test_request_code_cooldown_returns_429(client):
    client.post("/api/auth/signup/request-code", json={"phone_number": "01088880002"})
    r = client.post("/api/auth/signup/request-code", json={"phone_number": "01088880002"})
    assert r.status_code == 429  # RateLimitError → 429


def test_request_code_landline_returns_400(client):
    r = client.post("/api/auth/signup/request-code", json={"phone_number": "021234567"})
    assert r.status_code == 400  # ValueError(유선번호) → 400


def test_signup_verify_returns_access_token(client):
    phone = "01088880003"
    code = client.post(
        "/api/auth/signup/request-code", json={"phone_number": phone}
    ).json()["dev_code"]
    r = client.post("/api/auth/signup/verify", json={"phone_number": phone, "code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["user"]["phone_number"] == phone


def test_verify_wrong_code_returns_400(client):
    phone = "01088880004"
    code = client.post(
        "/api/auth/signup/request-code", json={"phone_number": phone}
    ).json()["dev_code"]
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"  # 실제 코드와 절대 겹치지 않게
    r = client.post("/api/auth/signup/verify", json={"phone_number": phone, "code": wrong})
    assert r.status_code == 400
