from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development")
    app_name: str = Field(default="ManuID")
    api_keys: str = Field(default="dev-key-change-me")
    database_url: str = Field(default="sqlite:///./manuid.db")
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    rate_limit_per_minute: int = Field(default=60)

    scrape_timeout_seconds: int = Field(default=20)
    scrape_max_html_bytes: int = Field(default=1_500_000)
    scrape_allowlist: str = Field(default="")

    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4.1-mini")
    enable_openai_enrichment: bool = Field(default=False)

    @property
    def api_key_list(self) -> list[str]:
        return [x.strip() for x in self.api_keys.split(",") if x.strip()]

    @property
    def scrape_allowlist_set(self) -> set[str]:
        return {x.strip().lower() for x in self.scrape_allowlist.split(",") if x.strip()}

    def is_domain_allowed(self, hostname: str) -> bool:
        allowlist = self.scrape_allowlist_set
        if not allowlist:
            return False
        host = hostname.lower()
        if host in allowlist:
            return True
        return any(host.endswith(f".{item}") for item in allowlist)


def _coerce_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.enable_openai_enrichment = _coerce_bool(settings.enable_openai_enrichment)
    return settings


def as_csv(items: Iterable[str]) -> str:
    return ",".join(items)
