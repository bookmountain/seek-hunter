import ipaddress
import secrets

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from seekhunter.config import get_env


def _in_cidrs(ip: str, cidrs: list[str]) -> bool:
    if ip in cidrs or f"{ip}/32" in cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(c, strict=False) for c in cidrs if "/" in c and c[0].isdigit())


def client_allowed(remote_ip: str, cf_ip: str | None, cidrs: list[str], public_ips: list[str]) -> bool:
    if cf_ip:
        return cf_ip in public_ips or _in_cidrs(cf_ip, cidrs)
    return _in_cidrs(remote_ip, cidrs)


async def ip_allowlist_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    if request.url.path == "/api/health":
        return await call_next(request)
    env = get_env()
    remote = request.client.host if request.client else ""
    if not client_allowed(remote, request.headers.get("cf-connecting-ip"), env.allowed_cidr_list,
                          env.allowed_public_ip_list):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return await call_next(request)


def require_write(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {get_env().api_write_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="write token required")
