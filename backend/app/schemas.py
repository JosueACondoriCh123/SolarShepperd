from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Measurement(BaseModel):
    metric: str
    value: float
    unit: str
    observed_at: datetime
    source: str
    quality_flags: list[str] = Field(default_factory=list)
    model_version: str | None = None
    station_id: str | None = None
    depth_cm: float | None = None


class TelemetryResponse(BaseModel):
    data: list[Measurement]
    count: int
    from_time: datetime
    to_time: datetime


class ForecastPointResponse(BaseModel):
    valid_at: datetime
    temperature_c: float | None
    relative_humidity_pct: float | None
    precipitation_probability_pct: float | None
    precipitation_mm: float | None
    uv_index: float | None
    wind_speed_m_s: float | None
    wind_gust_m_s: float | None
    et0_mm: float | None
    quality_flags: list[str]


class ForecastResponse(BaseModel):
    run_id: UUID | None
    source: str
    model_version: str | None
    generated_at: datetime | None
    fetched_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    data: list[ForecastPointResponse]
    count: int
    attribution: str


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    start: Coordinate
    end: Coordinate
    max_slope_deg: float = Field(default=18, gt=0, le=45)
    herd_tlu: float | None = Field(default=None, gt=0, le=100_000)
    uv_weight: float = Field(default=0.6, ge=0, le=2)
    forage_weight: float = Field(default=0.25, ge=0, le=0.5)
    water_weight: float = Field(default=0.2, ge=0, le=0.5)
    profile: Literal["fastest", "resource_aware"] = "resource_aware"


class RouteResponse(BaseModel):
    id: UUID
    status: Literal["complete"]
    total_distance_m: float
    estimated_time_s: float
    geojson: dict[str, Any]
    elevation_profile: list[dict[str, float]]
    diagnostics: dict[str, Any]
    quality_flags: list[str]
    not_applied_parameters: list[str] = Field(default_factory=list)
    profile: Literal["fastest", "resource_aware"] = "resource_aware"


class CalibrationStatus(BaseModel):
    status: Literal["CALIBRATION_REQUIRED", "READY"]
    sample_count: int
    active_model_version: str | None
    required_fields: list[str]
    message: str
    active_model: dict[str, Any] | None = None
    candidate_count: int = 0
    matched_sample_count: int = 0


class IngestionRunResponse(BaseModel):
    id: UUID
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    records_seen: int
    records_written: int
    latency_ms: int | None
    discovered_fields: list[str]
    diagnostics: dict[str, Any]
    error_code: str | None
    error_message: str | None


class APIErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DateRange(BaseModel):
    from_date: datetime
    to_date: datetime

    @field_validator("to_date")
    @classmethod
    def validate_order(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("from_date")
        if start and value < start:
            raise ValueError("to_date must be greater than or equal to from_date")
        return value
