import base64
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from seekhunter import auth, repo
from seekhunter.api import create_app
from seekhunter.config import Env, get_env
from seekhunter.db import get_session

PASSWORD = "correct horse battery staple"
SECRET = secrets.token_hex(32)
ORIGIN = "https://seekhunter.bookmountain.work"
# Cheap scrypt cost keeps the suite fast; production hashes use auth.DEFAULT_N.
FAST_HASH = auth.hash_password(PASSWORD, n=2**4)
TUNNEL_HEADERS = {"CF-Connecting-IP": "203.0.113.9"}
ME_ANON = {"authenticated": False, "username": None, "login_required": True}


# ---------- password hashing ----------

def test_hash_format_and_verify():
    h = auth.hash_password("s3cret-pass", n=2**4)
    parts = h.split("$")
    assert parts[0] == "scrypt" and parts[1:4] == ["16", "8", "3"]
    assert auth.verify_password("s3cret-pass", h)
    assert not auth.verify_password("wrong", h)


def test_hash_uses_random_salt():
    assert auth.hash_password("x", n=2**4) != auth.hash_password("x", n=2**4)


def test_default_cost_is_strong():
    assert auth.DEFAULT_N >= 2**15


BAD_HASHES = ["", "plain", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$AA$AA", "scrypt$16$8$1$!!$AA",
              "scrypt$15$8$1$AA$AA"]


@pytest.mark.parametrize("bad", BAD_HASHES)
def test_verify_rejects_malformed_hashes(bad):
    assert not auth.verify_password("x", bad)


def test_hash_password_cli(monkeypatch, capsys):
    from seekhunter import cli

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pw-from-prompt-long")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr(auth, "DEFAULT_N", 2**4)
    assert cli.main(["hash-password"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("scrypt$")
    assert auth.verify_password("pw-from-prompt-long", line)


# ---------- session tokens ----------

def test_session_roundtrip():
    tok = auth.make_session("book", SECRET, now=1000)
    assert auth.read_session(tok, SECRET, "book", now=1001) == "book"


def test_session_expired_rejected():
    tok = auth.make_session("book", SECRET, now=1000)
    assert auth.read_session(tok, SECRET, "book", now=1000 + auth.SESSION_TTL + 1) is None


def test_session_tampered_rejected():
    tok = auth.make_session("book", SECRET, now=1000)
    payload, sig = tok.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"u": "book", "iat": 1000, "exp": 10**12}).encode())
    assert auth.read_session(forged.decode().rstrip("=") + "." + sig, SECRET, "book", now=1001) is None
    assert auth.read_session(payload + "." + sig[:-2] + "AA", SECRET, "book", now=1001) is None
    assert auth.read_session("garbage", SECRET, "book", now=1001) is None
    assert auth.read_session("", SECRET, "book", now=1001) is None


def test_session_other_secret_or_user_rejected():
    tok = auth.make_session("book", SECRET, now=1000)
    assert auth.read_session(tok, secrets.token_hex(32), "book", now=1001) is None
    assert auth.read_session(tok, SECRET, "someone", now=1001) is None


# ---------- rate limiting ----------

def test_rate_limiter_per_ip_and_global():
    clock = [0.0]
    rl = auth.LoginRateLimiter(per_ip=5, global_limit=20, window=900, clock=lambda: clock[0])
    for _ in range(5):
        assert rl.allowed("1.1.1.1")
        rl.record_failure("1.1.1.1")
    assert not rl.allowed("1.1.1.1")
    assert rl.allowed("2.2.2.2")
    clock[0] = 901
    assert rl.allowed("1.1.1.1")
    for i in range(20):
        rl.record_failure(f"10.0.0.{i}")
    assert not rl.allowed("9.9.9.9")


def test_rate_limiter_success_clears_ip():
    rl = auth.LoginRateLimiter(per_ip=2, global_limit=20, window=900, clock=lambda: 0.0)
    rl.record_failure("1.1.1.1")
    rl.record_success("1.1.1.1")
    rl.record_failure("1.1.1.1")
    assert rl.allowed("1.1.1.1")


# ---------- config validation ----------

def test_login_disabled_without_username():
    assert not Env(auth_username=None).login_enabled
    auth.ensure_auth_config(Env(auth_username=None))  # no error


def test_auth_config_rejects_weak_secret_or_missing_hash():
    with pytest.raises(RuntimeError):
        auth.ensure_auth_config(Env(auth_username="book", auth_password_hash=FAST_HASH, session_secret="ab"))
    with pytest.raises(RuntimeError):
        auth.ensure_auth_config(Env(auth_username="book", auth_password_hash="", session_secret=SECRET))
    auth.ensure_auth_config(Env(auth_username="book", auth_password_hash=FAST_HASH, session_secret=SECRET))


# ---------- HTTP behaviour ----------

def _app(monkeypatch, tmp_path, *, login: bool, tunnel: bool):
    monkeypatch.setenv("API_WRITE_TOKEN", "t0k")
    monkeypatch.setenv("WRITE_REQUIRES_TOKEN", "false")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", ORIGIN)
    monkeypatch.setenv("ALLOWED_PUBLIC_IPS", "")
    monkeypatch.setenv("ALLOWED_CIDRS", "127.0.0.1/32,testclient/32")
    # TestClient's socket "IP" is the literal "testclient"; listing it as a tunnel proxy simulates
    # traffic arriving through cloudflared.
    monkeypatch.setenv("TUNNEL_PROXY_IPS", "testclient" if tunnel else "192.168.4.106")
    if login:
        monkeypatch.setenv("AUTH_USERNAME", "book")
        monkeypatch.setenv("AUTH_PASSWORD_HASH", FAST_HASH)
        monkeypatch.setenv("SESSION_SECRET", SECRET)
    else:
        monkeypatch.delenv("AUTH_USERNAME", raising=False)
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    get_env.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.ensure_seed(s)

    def override():
        with Session(engine) as s:
            yield s

    app = create_app(init=False)
    app.dependency_overrides[get_session] = override
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def tunnel(monkeypatch, tmp_path):
    c = _app(monkeypatch, tmp_path, login=True, tunnel=True)
    c.headers.update(TUNNEL_HEADERS)
    yield c
    get_env.cache_clear()


@pytest.fixture
def lan(monkeypatch, tmp_path):
    yield _app(monkeypatch, tmp_path, login=True, tunnel=False)
    get_env.cache_clear()


def _login(c, password=PASSWORD, username="book", origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return c.post("/api/auth/login", json={"username": username, "password": password}, headers=headers)


def test_tunnel_without_cookie_gets_401_on_api(tunnel):
    r = tunnel.get("/api/jobs")
    assert r.status_code == 401
    assert r.json() == {"detail": "authentication required"}


def test_tunnel_without_cookie_still_gets_spa_shell_and_assets(tunnel):
    r = tunnel.get("/")
    assert r.status_code == 200 and "spa" in r.text
    assert tunnel.get("/jobs/12").status_code == 200
    assert tunnel.get("/assets/app.js").text == "console.log(1)"


def test_tunnel_without_cf_header_is_forbidden(tunnel):
    del tunnel.headers["CF-Connecting-IP"]
    assert tunnel.get("/api/jobs").status_code == 403


def test_me_always_reachable(tunnel):
    assert tunnel.get("/api/auth/me").json() == ME_ANON


def test_health_exempt(tunnel):
    assert tunnel.get("/api/health").json() == {"ok": True}


def test_login_sets_secure_cookie_and_grants_access(tunnel):
    r = _login(tunnel)
    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("sh_session=")
    low = cookie.lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/", f"max-age={auth.SESSION_TTL}"):
        assert flag in low
    assert tunnel.get("/api/jobs").status_code == 200
    assert tunnel.get("/api/auth/me").json() == {**ME_ANON, "authenticated": True, "username": "book"}


def test_wrong_password_and_wrong_user_are_generic_401(tunnel):
    a = _login(tunnel, password="nope")
    b = _login(tunnel, username="admin")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "invalid username or password"}
    assert "set-cookie" not in a.headers


def test_failed_login_is_logged_without_password(tunnel, caplog):
    with caplog.at_level("WARNING"):
        _login(tunnel, password="hunter2-secret")
    assert "failed login" in caplog.text
    assert "203.0.113.9" in caplog.text
    assert "hunter2-secret" not in caplog.text


def test_login_rate_limited_per_ip(tunnel):
    for _ in range(5):
        assert _login(tunnel, password="nope").status_code == 401
    r = _login(tunnel)  # even the right password is refused while locked out
    assert r.status_code == 429
    assert r.json() == {"detail": "too many attempts, try again later"}
    # another client IP is unaffected
    tunnel.headers["CF-Connecting-IP"] = "198.51.100.7"
    assert _login(tunnel).status_code == 204


def test_login_global_backoff(tunnel):
    for i in range(20):
        tunnel.headers["CF-Connecting-IP"] = f"198.51.100.{i}"
        _login(tunnel, password="nope")
    tunnel.headers["CF-Connecting-IP"] = "192.0.2.200"
    assert _login(tunnel).status_code == 429


def test_logout_clears_cookie(tunnel):
    _login(tunnel)
    r = tunnel.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert r.status_code == 204
    assert 'sh_session=""' in r.headers["set-cookie"] or "max-age=0" in r.headers["set-cookie"].lower()
    assert tunnel.get("/api/jobs").status_code == 401


def test_csrf_origin_required_for_cookie_writes(tunnel):
    _login(tunnel)
    def put(headers):
        return tunnel.put("/api/ui-prefs/jobs", json={"page": "jobs"}, headers=headers).status_code

    assert put({}) == 403
    assert put({"Origin": "https://evil.example"}) == 403
    assert put({"Origin": "https://seekhunter.bookmountain.work.evil.example"}) == 403
    assert put({"Referer": "https://evil.example/x"}) == 403
    assert put({"Origin": ORIGIN}) == 200
    assert put({"Referer": ORIGIN + "/settings"}) == 200


def test_login_itself_requires_matching_origin(tunnel):
    assert _login(tunnel, origin="https://evil.example").status_code == 403
    assert _login(tunnel, origin=None).status_code == 403


def test_tampered_and_expired_cookie_rejected(tunnel):
    tunnel.cookies.set("sh_session", auth.make_session("book", SECRET, now=time.time()) + "x")
    assert tunnel.get("/api/jobs").status_code == 401
    old = time.time() - auth.SESSION_TTL - 5
    tunnel.cookies.set("sh_session", auth.make_session("book", SECRET, now=old))
    assert tunnel.get("/api/jobs").status_code == 401
    tunnel.cookies.set("sh_session", auth.make_session("book", SECRET, now=time.time()))
    assert tunnel.get("/api/jobs").status_code == 200


def test_security_headers_and_hsts_on_tunnel(tunnel):
    for path in ("/", "/api/jobs", "/api/auth/me"):
        r = tunnel.get(path)
        assert r.headers["strict-transport-security"].startswith("max-age=")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "same-origin"
    assert tunnel.get("/api/auth/me").headers["cache-control"] == "no-store"


def test_lan_without_cookie_allowed(lan):
    """The OpenClaw wrapper hits 127.0.0.1 directly with no browser and no cookie."""
    assert lan.get("/api/jobs").status_code == 200
    assert lan.put("/api/ui-prefs/jobs", json={"page": "jobs"}).status_code == 200
    assert lan.get("/api/auth/me").json() == {**ME_ANON, "login_required": False}
    assert "strict-transport-security" not in lan.get("/api/jobs").headers


def test_login_disabled_keeps_ip_allowlist_for_tunnel(monkeypatch, tmp_path):
    c = _app(monkeypatch, tmp_path, login=False, tunnel=True)
    c.headers.update(TUNNEL_HEADERS)
    assert c.get("/api/jobs").status_code == 403  # not in ALLOWED_PUBLIC_IPS
    monkeypatch.setenv("ALLOWED_PUBLIC_IPS", "203.0.113.9")
    get_env.cache_clear()
    assert c.get("/api/jobs").status_code == 200
    assert c.get("/api/auth/me").json()["login_required"] is False
    assert _login(c).status_code == 404
    get_env.cache_clear()


def test_hash_password_cli_reads_stdin_and_rejects_short(monkeypatch, capsys):
    import io

    from seekhunter import cli

    monkeypatch.setattr(auth, "DEFAULT_N", 2**4)
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-enough-password\n"))
    assert cli.main(["hash-password"]) == 0
    assert auth.verify_password("a-long-enough-password", capsys.readouterr().out.strip())
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["hash-password"]) == 1


def test_app_refuses_to_start_with_login_but_no_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_USERNAME", "book")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", FAST_HASH)
    monkeypatch.setenv("SESSION_SECRET", "")
    get_env.cache_clear()
    with pytest.raises(RuntimeError):
        create_app(init=False)


def test_logged_in_session_may_write_even_when_token_required(tunnel, monkeypatch):
    monkeypatch.setenv("WRITE_REQUIRES_TOKEN", "true")
    get_env.cache_clear()
    _login(tunnel)
    r = tunnel.put("/api/ui-prefs/jobs", json={"page": "jobs"}, headers={"Origin": ORIGIN})
    assert r.status_code == 200
