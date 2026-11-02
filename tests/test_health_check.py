"""외부 가동 확인 `GET /api/health` — Route 53 이 부른다.

DB 가 끊기면 실패해야 경보가 울리고, 하루 4만 건이 넘으므로 요청 로그를 밀어내면 안 된다.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from database import get_db
from main import app


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_answers_without_auth_when_db_is_reachable(client, db):
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fails_without_leaking_the_cause_when_db_is_down(client):
    class BrokenSession:
        def execute(self, _statement):
            raise OperationalError("SELECT 1", {}, Exception("내부 접속 정보"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()

    response = client.get("/api/health")

    assert response.status_code == 503
    assert "내부 접속 정보" not in response.text


def test_is_left_out_of_the_request_log(client, db, caplog):
    app.dependency_overrides[get_db] = lambda: db

    with caplog.at_level(logging.INFO, logger="kcal"):
        client.get("/api/health")
        client.get("/api/plans")

    assert "path=/api/health" not in caplog.text
    assert "path=/api/plans" in caplog.text
