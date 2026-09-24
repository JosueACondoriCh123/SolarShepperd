from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_name: str = "SolarShepherd API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://solarshepherd:solarshepherd@localhost:5432/solarshepherd"
    )
    redis_url: str = "redis://localhost:6379/0"
    api_admin_token: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Authentication is permissive only for local development. Production
    # refuses to boot in development mode in app.main.
    auth_mode: str = "development"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    system_owner_emails: list[str] = Field(default_factory=list)
    turnstile_site_key: str = ""
    resend_api_key: str = ""
    email_from: str = "SolarShepherd <no-reply@example.com>"
    sample_evidence_bucket: str = "sample-evidence"
    response_evidence_bucket: str = "response-evidence"
    reports_bucket: str = "reports"
    signed_url_ttl_seconds: int = 300
    local_storage_path: str = "/data/operational"

    conduit_api_url: str = "https://conduit.jhubafrica.com/data.php"
    conduit_api_key: str = ""
    conduit_email: str = ""
    conduit_field_map_json: str = "{}"
    conduit_station_id: str = "jkuat-conduit"
    conduit_dataset_mode: bool = False
    conduit_data_dir: str = "data"

    pilot_name: str = "JKUAT"
    pilot_lat: float = -1.1018
    pilot_lon: float = 37.0144
    pilot_radius_km: float = 10.0
    pilot_timezone: str = "Africa/Nairobi"
    h3_resolution: int = 9
    stac_max_cloud_percent: float = 30.0
    stac_lookback_days: int = 60
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"
    open_meteo_api_url: str = "https://api.open-meteo.com/v1/forecast"
    aviation_weather_api_url: str = "https://aviationweather.gov/api/data/metar"
    forecast_hours: int = 72

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("system_owner_emails", mode="before")
    @classmethod
    def parse_owner_emails(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(",") if part.strip()]
        return value

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_issuer}/.well-known/jwks.json"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    @property
    def conduit_field_map(self) -> dict[str, str]:
        try:
            value = json.loads(self.conduit_field_map_json)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @property
    def conduit_configured(self) -> bool:
        return bool(self.conduit_api_key and self.conduit_email)


@lru_cache
def get_settings() -> Settings:
    return Settings()
