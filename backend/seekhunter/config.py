from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/seekhunter.db"
    resume_dir: Path = Path("../../book-cv/latex/sections/resume")
    latex_dir: Path = Path("../../book-cv/latex")
    tectonic_bin: str = "/usr/local/bin/tectonic"
    static_dir: Path = Path("../frontend/dist")
    data_dir: Path = Path("./data")
    anthropic_api_key: str | None = None
    brave_api_key: str | None = None
    api_write_token: str = "dev-token"
    allowed_cidrs: str = "127.0.0.1/32,192.168.4.0/24,100.64.0.0/10"
    allowed_public_ips: str = ""
    tunnel_proxy_ips: str = "192.168.4.106"
    telegram_target: str = "1635495359"
    openclaw_bin: str = "openclaw"
    openclaw_agent: str = "seekhunter-scorer"
    public_url: str = "http://localhost:8090"
    seekhunter_dev: bool = False
    # Resume-Matcher API for server-side calls (e.g. http://192.168.4.106:3101); empty disables it.
    rm_base_url: str = ""
    # Where the browser opens Resume-Matcher links; empty = rm_base_url.
    rm_public_url: str = ""

    @property
    def rm_link_base(self) -> str:
        return (self.rm_public_url or self.rm_base_url or "").strip().rstrip("/")
    # The IP allowlist already limits who can reach the app; when False, writes from allowed
    # networks don't need the bearer token (the OpenClaw wrapper still sends it harmlessly).
    write_requires_token: bool = True
    # Login for traffic arriving through the Cloudflare tunnel. Unset AUTH_USERNAME = login disabled
    # (dev/tests); the tunnel then falls back to the ALLOWED_PUBLIC_IPS allowlist.
    auth_username: str | None = None
    # `seekhunter hash-password` output: scrypt$n$r$p$salt_b64$hash_b64
    auth_password_hash: str = ""
    # Hex, >= 32 random bytes (`openssl rand -hex 32`). Rotating it logs everyone out.
    session_secret: str = ""

    @property
    def login_enabled(self) -> bool:
        return bool((self.auth_username or "").strip())

    # Re-check SEEK applicant numbers when a job is opened (tests turn it off in conftest).
    refresh_insights_on_view: bool = True

    @property
    def allowed_cidr_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_cidrs.split(",") if c.strip()]

    @property
    def allowed_public_ip_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_public_ips.split(",") if c.strip()]

    @property
    def tunnel_proxy_ip_list(self) -> list[str]:
        return [c.strip() for c in self.tunnel_proxy_ips.split(",") if c.strip()]


@lru_cache
def get_env() -> Env:
    return Env()
