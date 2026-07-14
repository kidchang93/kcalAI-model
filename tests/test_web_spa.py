"""Expo 웹 export 서빙 회귀.

`/auth` 가 404 면 **카카오 콜백(`/auth?code=...`)이 끊겨 웹 로그인이 불가능해진다.**
Expo 는 라우트마다 `<route>.html` 을 만드는데 기본 StaticFiles 는 그걸 못 찾는다.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main import ExpoWebFiles


@pytest.fixture
def client(tmp_path):
    # Expo export 산출물 흉내: 라우트마다 <route>.html
    (tmp_path / "index.html").write_text("home")
    (tmp_path / "auth.html").write_text("auth screen")
    (tmp_path / "groups").mkdir()
    (tmp_path / "groups" / "create.html").write_text("create group")

    app = FastAPI()
    app.mount("/", ExpoWebFiles(directory=str(tmp_path), html=True), name="webapp")

    with TestClient(app) as test_client:
        yield test_client


def test_route_without_extension_serves_the_exported_html(client):
    response = client.get("/auth")

    assert response.status_code == 200
    assert response.text == "auth screen"


def test_nested_route_is_served(client):
    assert client.get("/groups/create").text == "create group"


def test_root_still_serves_index(client):
    assert client.get("/").status_code == 200


def test_unknown_path_is_still_404(client):
    # SPA 폴백으로 아무 경로나 index 를 주면 진짜 404 를 숨기게 된다.
    assert client.get("/definitely-not-a-route").status_code == 404
