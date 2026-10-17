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
    # Self-hosted Resume-Matcher (e.g. http://192.168.4.106:3100); empty disables the integration.
    rm_base_url: str = ""
    # The IP allowlist already limits who can reach the app; when False, writes from allowed
    # networks don't need the bearer token (the OpenClaw wrapper still sends it harmlessly).
    write_requires_token: bool = True

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
