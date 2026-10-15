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
    assert r.json()["sms_code"] == "845123"
    assert client.get("/code", params={"keyword": "某平台"}, headers=H).json()["sms_code"] == "845123"
    assert client.get("/code", headers=H).status_code == 404


def test_form_and_keyword(client):
    client.post("/push", data={"text": "A平台 code: 1111"}, headers=H)
    client.post("/push", data={"msg": "B平台 验证码 2222"}, headers=H)
    assert client.get("/code", params={"keyword": "A平台"}, headers=H).json()["sms_code"] == "1111"


def test_since_and_latest(client):
    client.post("/push", json={"content": "验证码 9999"}, headers=H)
    assert client.get("/code", params={"since": time.time() + 100}, headers=H).status_code == 404
    assert len(client.get("/latest", params={"n": 5}, headers=H).json()) == 1


def test_no_code(client):
    assert client.post("/push", json={"body": "hello"}, headers=H).json()["sms_code"] is None
    assert client.get("/code", headers=H).status_code == 404


PDD = "【拼多多】验证码：600162，您正在验证拼多多管理后台手机号，请于10分钟内完成验证，若非本人操作，请忽略此短信。"


def test_parse_pdd(client):
    r = client.post("/push", json={"body": PDD}, headers=H).json()
    assert r["platform"] == "拼多多" and r["sms_code"] == "600162"
    assert client.get("/code", params={"platform": "淘宝"}, headers=H).status_code == 404
    j = client.get("/code", params={"platform": "拼多多"}, headers=H).json()
    assert j["platform"] == "拼多多" and j["sms_code"] == "600162"


def test_trailing_and_none():
    from app.main import extract_platform, extract_code
    assert extract_platform("您的验证码是 4821，5分钟有效。【京东】") == "京东"
    assert extract_platform("[Steam] code 9911") == "Steam"
    assert extract_platform("您的验证码是 4821") is None
    assert extract_code("Your verification code: AB12CD, expires soon") == "AB12CD"
    assert extract_code("验证码 4821 有效") == "4821"


def test_migrate_old_schema(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE sms(id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, body TEXT, code TEXT, created REAL, used INTEGER DEFAULT 0)")
    c.execute("INSERT INTO sms(sender,body,code,created) VALUES('x','验证码 1234',?,?)", ("1234", time.time()))
    c.commit(); c.close()
    monkeypatch.setenv("RELAY_TOKEN", "t" * 40)
    monkeypatch.setenv("DB_PATH", str(db))
    import app.main as m
    importlib.reload(m)
    with TestClient(m.app) as cl:
        j = cl.get("/code", headers=H).json()
        assert j["sms_code"] == "1234" and j["platform"] is None
