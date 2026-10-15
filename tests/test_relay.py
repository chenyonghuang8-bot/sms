import importlib, time
import pytest
from fastapi.testclient import TestClient

H = {"X-Token": "t" * 40}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_TOKEN", "t" * 40)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    import app.main as m
    importlib.reload(m)
    with TestClient(m.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_auth(client):
    assert client.post("/push", json={"body": "验证码 1234"}).status_code == 401
    assert client.get("/code", headers={"X-Token": "bad"}).status_code == 401


def test_json_push_and_fetch_once(client):
    r = client.post("/push", json={"body": "【某平台】您的验证码是 845123，5分钟内有效", "from": "10690"}, headers=H)
    assert r.json()["code"] == "845123"
    assert client.get("/code", params={"keyword": "某平台"}, headers=H).json()["code"] == "845123"
    assert client.get("/code", headers=H).status_code == 404


def test_form_and_keyword(client):
    client.post("/push", data={"text": "A平台 code: 1111"}, headers=H)
    client.post("/push", data={"msg": "B平台 验证码 2222"}, headers=H)
    assert client.get("/code", params={"keyword": "A平台"}, headers=H).json()["code"] == "1111"


def test_since_and_latest(client):
    client.post("/push", json={"content": "验证码 9999"}, headers=H)
    assert client.get("/code", params={"since": time.time() + 100}, headers=H).status_code == 404
    assert len(client.get("/latest", params={"n": 5}, headers=H).json()) == 1


def test_no_code(client):
    assert client.post("/push", json={"body": "hello"}, headers=H).json()["code"] is None
    assert client.get("/code", headers=H).status_code == 404
