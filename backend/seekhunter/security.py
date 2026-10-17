import ipaddress
import secrets

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

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


async def ip_allowlist_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    if request.url.path == "/api/health":
        return await call_next(request)
    env = get_env()
    remote = request.client.host if request.client else ""
    if not client_allowed(remote, request.headers.get("cf-connecting-ip"), env.allowed_cidr_list,
                          env.allowed_public_ip_list, env.tunnel_proxy_ip_list):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return await call_next(request)


def require_write(authorization: str | None = Header(default=None)) -> None:
    env = get_env()
    if not env.write_requires_token:
        return  # request already passed the IP allowlist middleware
    expected = f"Bearer {env.api_write_token}"
    if not authorization or not secrets.compare_digest(
        authorization.encode("latin-1", "replace"), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="write token required")
