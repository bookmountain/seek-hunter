"""Username/password login for traffic arriving through the Cloudflare tunnel.

Passwords are hashed with scrypt (stdlib, no extra deps). Sessions are stateless: the cookie holds
a base64url JSON payload {u, iat, exp} plus an HMAC-SHA256 signature over it, keyed by
SESSION_SECRET. Rotating the secret invalidates every session.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from seekhunter.config import Env, get_env

log = logging.getLogger("seekhunter.auth")

COOKIE_NAME = "sh_session"
SESSION_TTL = 30 * 24 * 3600
MIN_SECRET_BYTES = 32
MAX_TOKEN_LEN = 1024

# OWASP Password Storage Cheat Sheet: N=2^15 (32 MiB), r=8, p=3 is one of the recommended
# equal-strength scrypt configurations; it keeps memory per attempt modest on a small VPS.
DEFAULT_N = 2**15
DEFAULT_R = 8
DEFAULT_P = 3
SALT_BYTES = 16
KEY_BYTES = 32
# Upper bounds so a malformed hash in the env can't make one login eat gigabytes.
MAX_N, MAX_R, MAX_P = 2**20, 32, 16


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    maxmem = 2 * 128 * r * (n + p) + 2**20
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=maxmem)


def hash_password(password: str, n: int | None = None, r: int = DEFAULT_R, p: int | None = None) -> str:
    n = DEFAULT_N if n is None else n
    p = DEFAULT_P if p is None else p
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, n, r, p, KEY_BYTES)
    return f"scrypt${n}${r}${p}${_b64e(salt)}${_b64e(key)}"


def _parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = (stored or "").strip().split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, key = _b64d(parts[4]), _b64d(parts[5])
    except (ValueError, binascii.Error):
        return None
    if not (1 < n <= MAX_N and n & (n - 1) == 0 and 0 < r <= MAX_R and 0 < p <= MAX_P):
        return None
    if not salt or not key:
        return None
    return n, r, p, salt, key


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    n, r, p, salt, key = parsed
    try:
        candidate = _scrypt(password, salt, n, r, p, len(key))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(candidate, key)


# ---------- sessions ----------

def _secret_bytes(secret: str) -> bytes:
    return bytes.fromhex(secret.strip())


def _sign(payload_b64: str, secret: str) -> str:
    return _b64e(hmac.new(_secret_bytes(secret), payload_b64.encode(), hashlib.sha256).digest())


def make_session(username: str, secret: str, now: float | None = None) -> str:
    iat = int(time.time() if now is None else now)
    payload = _b64e(json.dumps({"u": username, "iat": iat, "exp": iat + SESSION_TTL},
                               separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, secret)}"


def read_session(token: str | None, secret: str, expected_user: str, now: float | None = None) -> str | None:
    """Return the username for a valid, unexpired token signed with `secret`; None otherwise."""
    if not token or len(token) > MAX_TOKEN_LEN or token.count(".") != 1:
        return None
    payload_b64, sig = token.split(".")
    try:
        expected_sig = _sign(payload_b64, secret)
    except ValueError:
        return None
    if not hmac.compare_digest(sig.encode(), expected_sig.encode()):
        return None
    try:
        data = json.loads(_b64d(payload_b64))
        user, exp = data["u"], int(data["exp"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    now = time.time() if now is None else now
    if not isinstance(user, str) or exp <= now:
        return None
    if not hmac.compare_digest(user.encode(), expected_user.encode()):
        return None
    return user


def session_user(request: Request, env: Env) -> str | None:
    if not env.login_enabled:
        return None
    username = (env.auth_username or "").strip()
    return read_session(request.cookies.get(COOKIE_NAME), env.session_secret, username)


# ---------- rate limiting ----------

class LoginRateLimiter:
    """In-memory sliding-window counter of failed logins, per client IP and globally."""

    def __init__(self, per_ip: int = 5, global_limit: int = 20, window: float = 900,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.per_ip = per_ip
        self.global_limit = global_limit
        self.window = window
        self.clock = clock
        self._ip: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        while self._all and self._all[0] <= cutoff:
            self._all.popleft()
        for ip in list(self._ip):
            q = self._ip[ip]
            while q and q[0] <= cutoff:
                q.popleft()
            if not q:
                del self._ip[ip]

    def allowed(self, ip: str) -> bool:
        with self._lock:
            self._prune(self.clock())
            return len(self._all) < self.global_limit and len(self._ip.get(ip, ())) < self.per_ip

    def record_failure(self, ip: str) -> None:
        with self._lock:
            now = self.clock()
            self._all.append(now)
            self._ip.setdefault(ip, deque()).append(now)

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._ip.pop(ip, None)


# ---------- config ----------

def ensure_auth_config(env: Env) -> None:
    """Fail closed: refuse to start with login enabled but a missing/weak hash or secret."""
    if not env.login_enabled:
        return
    if _parse_hash(env.auth_password_hash) is None:
        raise RuntimeError("AUTH_USERNAME is set but AUTH_PASSWORD_HASH is missing or malformed. "
                           "Generate one with `seekhunter hash-password`.")
    try:
        secret = _secret_bytes(env.session_secret)
    except ValueError:
        secret = b""
    if len(secret) < MIN_SECRET_BYTES:
        raise RuntimeError(f"SESSION_SECRET must be at least {MIN_SECRET_BYTES} random bytes as hex. "
                           "Generate one with `openssl rand -hex 32`.")


# ---------- HTTP ----------

def client_ip(request: Request) -> str:
    """The real client: CF-Connecting-IP for tunnel traffic (set by the middleware), else the socket."""
    ip = getattr(request.state, "client_ip", None)
    if ip:
        return ip
    return request.client.host if request.client else ""


class LoginIn(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=1024)


GENERIC_FAIL = "invalid username or password"
RATE_LIMITED = "too many attempts, try again later"


def install(app: FastAPI) -> None:
    app.state.login_limiter = LoginRateLimiter()
    # scrypt is memory-hard; cap concurrent hashes so a burst of logins can't exhaust RAM.
    hashing = threading.BoundedSemaphore(2)
    router = APIRouter(prefix="/api/auth")

    @router.post("/login", status_code=204)
    def login(body: LoginIn, request: Request) -> Response:
        env = get_env()
        if not env.login_enabled:
            raise HTTPException(404, "login disabled")
        ip = client_ip(request)
        limiter: LoginRateLimiter = request.app.state.login_limiter
        if not limiter.allowed(ip):
            log.warning("login rate-limited for %s", ip)
            raise HTTPException(429, RATE_LIMITED)
        if not hashing.acquire(timeout=10):
            raise HTTPException(429, RATE_LIMITED)
        try:
            user_ok = hmac.compare_digest(body.username.encode(), env.auth_username.strip().encode())
            # Always run scrypt, even for a wrong username, so timing doesn't reveal which was wrong.
            pw_ok = verify_password(body.password, env.auth_password_hash)
        finally:
            hashing.release()
        if not (user_ok and pw_ok):
            limiter.record_failure(ip)
            log.warning("failed login from %s", ip)
            raise HTTPException(401, GENERIC_FAIL)
        limiter.record_success(ip)
        log.info("login from %s", ip)
        response = Response(status_code=204)
        response.set_cookie(COOKIE_NAME, make_session(env.auth_username.strip(), env.session_secret),
                            max_age=SESSION_TTL, httponly=True, secure=True, samesite="lax", path="/")
        return response

    @router.post("/logout", status_code=204)
    def logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=True, samesite="lax")
        return response

    @router.get("/me")
    def me(request: Request) -> dict:
        env = get_env()
        user = session_user(request, env)
        required = env.login_enabled and bool(getattr(request.state, "via_tunnel", False))
        return {"authenticated": user is not None, "username": user, "login_required": required}

    app.include_router(router)
