from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    onboarding_completed: bool | None = None
    notification_preferences: dict[str, bool] | None = None


class MissionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=4000)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    route_run_id: UUID | None = None
    herd_tlu: float | None = Field(default=None, gt=0, le=100_000)
    notes: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def validate_schedule(self) -> MissionCreate:
        if self.scheduled_start and self.scheduled_start.tzinfo is None:
            raise ValueError("scheduled_start must include a timezone")
        if self.scheduled_end and self.scheduled_end.tzinfo is None:
            raise ValueError("scheduled_end must include a timezone")
        if (
            self.scheduled_start
            and self.scheduled_end
            and self.scheduled_end < self.scheduled_start
        ):
            raise ValueError("scheduled_end must not be before scheduled_start")
        return self


class MissionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "planned", "active", "completed", "cancelled"] | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    route_run_id: UUID | None = None
    herd_tlu: float | None = Field(default=None, gt=0, le=100_000)
    notes: str | None = Field(default=None, max_length=8000)
    revision: int = Field(ge=1)


class SampleSubmissionCreate(BaseModel):
    external_reference: str | None = Field(default=None, max_length=128)
    sampled_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    dry_matter_kg_ha: float = Field(gt=0, le=1_000_000)
    method: str = Field(min_length=2, max_length=180)
    quadrat_area_m2: float = Field(gt=0, le=10_000)
    mission_id: UUID | None = Field(default=None)

    @field_validator("sampled_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sampled_at must include a timezone")
        return value


class SampleReview(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def rejection_requires_notes(self) -> SampleReview:
        if self.decision == "rejected" and not self.notes.strip():
            raise ValueError("rejection notes are required")
        return self


class ReportCreate(BaseModel):
    mission_id: UUID
    title: str | None = Field(default=None, max_length=180)


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    kind: Literal["forecast_threshold", "telemetry_stale", "mission_reminder", "sample_review"]
    metric: str | None = None
    comparator: Literal[">", ">=", "<", "<="] | None = None
    threshold: float | None = None
    lookahead_hours: int = Field(default=24, ge=1, le=168)
    cooldown_minutes: int = Field(default=180, ge=15, le=10_080)
    channels: list[Literal["in_app", "email"]] = Field(default_factory=lambda: ["in_app"])
    enabled: bool = True
    severity: Literal["advisory", "warning", "critical"] = "warning"
    response_mode: Literal["notify_only", "case_and_mission"] = "case_and_mission"

    @model_validator(mode="after")
    def validate_threshold(self) -> AlertRuleCreate:
        if self.kind in {"forecast_threshold", "telemetry_stale"}:
            if self.threshold is None or self.comparator is None:
                raise ValueError("threshold rules require comparator and threshold")
        if self.kind == "forecast_threshold" and self.metric not in {
            "temperature_c",
            "precipitation_probability_pct",
            "precipitation_mm",
            "uv_index",
            "wind_speed_m_s",
            "wind_gust_m_s",
        }:
            raise ValueError("unsupported forecast metric")
        return self


class AlertRulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    threshold: float | None = None
    comparator: Literal[">", ">=", "<", "<="] | None = None
    lookahead_hours: int | None = Field(default=None, ge=1, le=168)
    cooldown_minutes: int | None = Field(default=None, ge=15, le=10_080)
    channels: list[Literal["in_app", "email"]] | None = None
    enabled: bool | None = None
    severity: Literal["advisory", "warning", "critical"] | None = None
    response_mode: Literal["notify_only", "case_and_mission"] | None = None


class ResponseCaseAcknowledge(BaseModel):
    revision: int


class ResponseCaseRoute(BaseModel):
    route_id: UUID
    revision: int


class ResponseCaseStart(BaseModel):
    revision: int


class ResponseCaseComplete(BaseModel):
    revision: int


class ResponseCaseClose(BaseModel):
    resolution_notes: str = Field(min_length=3)
    revision: int


class ResponseCaseDismiss(BaseModel):
    reason: str = Field(min_length=3)
    revision: int


class ResponseUpdateCreate(BaseModel):
    notes: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class MemberPatch(BaseModel):
    status: Literal["active", "suspended"]


class DataSourcePatch(BaseModel):
    enabled: bool | None = None
    schedule: str | None = Field(default=None, max_length=96)
    mapping: dict[str, Any] | None = None

