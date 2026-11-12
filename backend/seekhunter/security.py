import ipaddress
import secrets
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from seekhunter.auth import session_user
from seekhunter.config import Env, get_env

WEAK_WRITE_TOKENS = {"dev-token", "change-me"}
MIN_WRITE_TOKEN_LEN = 24


def ensure_safe_write_token(env: Env) -> None:
    """Refuse to start with a missing/default/short write token outside dev mode."""
    if env.seekhunter_dev:
        return
    token = env.api_write_token
    if not token or token in WEAK_WRITE_TOKENS or len(token) < MIN_WRITE_TOKEN_LEN:
        raise RuntimeError(
            "API_WRITE_TOKEN is missing, default, or shorter than "
            f"{MIN_WRITE_TOKEN_LEN} chars. Set a strong token, or SEEKHUNTER_DEV=1 for local dev."
        )


def _in_cidrs(ip: str, entries: list[str]) -> bool:
    """Match `ip` against a list of entries that may be literal hosts, or IPv4/IPv6 networks."""
    if ip in entries or f"{ip}/32" in entries:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in entries:
        if "/" not in entry:
            continue
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in net:
            return True
    return False


def client_allowed(remote_ip: str, cf_ip: str | None, cidrs: list[str], public_ips: list[str],
                   tunnel_ips: list[str]) -> bool:
    cf_ip = (cf_ip or "").strip() or None
    if remote_ip in tunnel_ips:
        # cloudflared itself connects from the LAN, so its own IP must never stand in for the
        # real client; the request is only trusted when it carries a CF-Connecting-IP header.
        if not cf_ip:
            return False
        return _in_cidrs(cf_ip, public_ips) or _in_cidrs(cf_ip, cidrs)
    if cf_ip:
        return _in_cidrs(cf_ip, public_ips) or _in_cidrs(cf_ip, cidrs)
    return _in_cidrs(remote_ip, cidrs)


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
HSTS = "max-age=31536000"


def _origin_of(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def same_origin(request: Request, public_url: str) -> bool:
    """CSRF guard: an unsafe request must say (Origin, else Referer) it came from our own site."""
    expected = _origin_of(public_url)
    if not expected:
        return False
    origin = request.headers.get("origin")
    if origin:
        return _origin_of(origin) == expected
    referer = request.headers.get("referer")
    return bool(referer) and _origin_of(referer) == expected


def _tunnel_login_gate(request: Request, env: Env) -> JSONResponse | None:
    """Access rules for tunnel traffic when login is enabled. None means: let it through."""
    path = request.url.path
    if request.method not in SAFE_METHODS and not same_origin(request, env.public_url):
        return JSONResponse({"detail": "cross-origin request rejected"}, status_code=403)
    if path == "/api/health" or path.startswith("/api/auth/"):
        return None
    user = session_user(request, env)
    request.state.user = user
    if user:
        return None
    if path == "/api" or path.startswith("/api/") or request.method not in SAFE_METHODS:
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return None  # SPA shell / static assets only: every data route lives under /api


def _gate(request: Request, env: Env) -> JSONResponse | None:
    remote = request.client.host if request.client else ""
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip() or None
    via_tunnel = remote in env.tunnel_proxy_ip_list
    request.state.via_tunnel = via_tunnel
    request.state.client_ip = cf_ip if via_tunnel and cf_ip else remote
    if request.url.path == "/api/health":
        return None
    if via_tunnel and env.login_enabled:
        if not cf_ip:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return _tunnel_login_gate(request, env)
    if not client_allowed(remote, cf_ip, env.allowed_cidr_list, env.allowed_public_ip_list,
                          env.tunnel_proxy_ip_list):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return None


async def access_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    """IP allowlist for LAN/Tailscale, login for the Cloudflare tunnel, security headers for all."""
    env = get_env()
    denied = _gate(request, env)
    response = denied if denied is not None else await call_next(request)
    for name, value in BASE_SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if getattr(request.state, "via_tunnel", False):
        response.headers.setdefault("Strict-Transport-Security", HSTS)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# Backwards-compatible name.
ip_allowlist_middleware = access_middleware


def require_write(request: Request, authorization: str | None = Header(default=None)) -> None:
    env = get_env()
    if not env.write_requires_token:
        return  # request already passed the access middleware (IP allowlist or login)
    if getattr(request.state, "user", None):
        return  # a logged-in browser session (Origin-checked by the middleware) may write
    expected = f"Bearer {env.api_write_token}"
    if not authorization or not secrets.compare_digest(
        authorization.encode("latin-1", "replace"), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="write token required")
