import asyncio, hmac, os, re, sqlite3, time
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Request, Query

DB_PATH = os.environ.get("DB_PATH", "/data/sms.db")
CODE_TTL = int(os.environ.get("CODE_TTL", "300"))
KEEP_SECONDS = int(os.environ.get("KEEP_SECONDS", "86400"))
CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


def token() -> str:
    t = os.environ.get("RELAY_TOKEN", "")
    if not t:
        raise RuntimeError("RELAY_TOKEN is required")
    return t


def db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sms(
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, body TEXT,
            sms_code TEXT, platform TEXT, created REAL, used INTEGER DEFAULT 0)""")
        cols = {r[1] for r in c.execute("PRAGMA table_info(sms)")}
        if "code" in cols and "sms_code" not in cols:
            c.execute("ALTER TABLE sms RENAME COLUMN code TO sms_code")
        if "platform" not in cols:
            c.execute("ALTER TABLE sms ADD COLUMN platform TEXT")


def cleanup():
    with db() as c:
        c.execute("DELETE FROM sms WHERE created < ?", (time.time() - KEEP_SECONDS,))


def auth(x_token: Optional[str]):
    if not x_token or not hmac.compare_digest(x_token.encode(), token().encode()):
        raise HTTPException(401, "invalid token")


KW = r"(?:验证码|校验码|动态码|code)"
SIG_HEAD = re.compile(r"^\s*(?:【([^】]{1,30})】|\[([^\]]{1,30})\])")
SIG_TAIL = re.compile(r"(?:【([^】]{1,30})】|\[([^\]]{1,30})\])\s*$")


def extract_platform(body: str) -> Optional[str]:
    for r in (SIG_HEAD, SIG_TAIL):
        m = r.search(body)
        if m:
            return (m.group(1) or m.group(2)).strip() or None
    return None


def extract_code(body: str) -> Optional[str]:
    m = re.search(KW + r"[^\d]{0,10}(\d{4,8})(?!\d)", body, re.I)
    if m:
        return m.group(1)
    m = re.search(KW + r"[^A-Za-z0-9]{0,10}(?=[A-Za-z]*\d)([A-Za-z0-9]{4,8})(?![A-Za-z0-9])", body, re.I)
    if m:
        return m.group(1)
    m = CODE_RE.search(body)
    return m.group(1) if m else None


async def _loop():
    while True:
        await asyncio.sleep(600)
        try:
            cleanup()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app):
    token()
    init_db()
    cleanup()
    t = asyncio.create_task(_loop())
    yield
    t.cancel()


app = FastAPI(title="SMS Relay", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/push")
async def push(request: Request, x_token: Optional[str] = Header(None)):
    auth(x_token)
    ct = request.headers.get("content-type", "")
    data = {}
    try:
        if "json" in ct:
            data = await request.json()
        elif "form" in ct:
            data = dict(await request.form())
        else:
            data = {"body": (await request.body()).decode("utf-8", "replace")}
    except Exception:
        raise HTTPException(400, "bad payload")
    if not isinstance(data, dict):
        raise HTTPException(400, "bad payload")
    body = next((str(data[k]) for k in ("body", "text", "msg", "content") if data.get(k)), "")
    sender = next((str(data[k]) for k in ("from", "sender") if data.get(k)), "")
    if not body:
        raise HTTPException(400, "empty body")
    code, platform = extract_code(body), extract_platform(body)
    with db() as c:
        cur = c.execute("INSERT INTO sms(sender,body,sms_code,platform,created) VALUES(?,?,?,?,?)",
                        (sender, body, code, platform, time.time()))
    return {"ok": True, "id": cur.lastrowid, "platform": platform, "sms_code": code}


@app.get("/code")
def get_code(keyword: str = "", since: float = 0, platform: Optional[str] = None, x_token: Optional[str] = Header(None)):
    auth(x_token)
    lo = max(since, time.time() - CODE_TTL)
    with db() as c:
        c.isolation_level = None
        c.execute("BEGIN IMMEDIATE")
        sql = ("SELECT * FROM sms WHERE used=0 AND sms_code IS NOT NULL AND created>=? "
               "AND (body LIKE ? OR sender LIKE ?)")
        args = [lo, f"%{keyword}%", f"%{keyword}%"]
        if platform:
            sql += " AND platform=?"
            args.append(platform)
        row = c.execute(sql + " ORDER BY created DESC LIMIT 1", args).fetchone()
        if not row:
            c.execute("COMMIT")
            raise HTTPException(404, "no code")
        c.execute("UPDATE sms SET used=1 WHERE id=?", (row["id"],))
        c.execute("COMMIT")
    return {"platform": row["platform"], "sms_code": row["sms_code"], "sender": row["sender"], "body": row["body"], "created": row["created"]}


@app.get("/latest")
def latest(n: int = Query(10, ge=1, le=100), x_token: Optional[str] = Header(None)):
    auth(x_token)
    with db() as c:
        rows = c.execute("SELECT * FROM sms ORDER BY created DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]
