from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Pilot(Base, TimestampMixin):
    __tablename__ = "pilots"

    slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True)
    center: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    boundary: Mapped[Any] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    radius_km: Mapped[float] = mapped_column(Float, default=10.0)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Nairobi")
    observation_stations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    source: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="running")
    requested_from: Mapped[date | None] = mapped_column(Date)
    requested_to: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    discovered_fields: Mapped[list[str]] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class RawSourcePayload(Base):
    __tablename__ = "raw_source_payloads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    source: Mapped[str] = mapped_column(String(32), index=True)
    requested_from: Mapped[date | None] = mapped_column(Date)
    requested_to: Mapped[date | None] = mapped_column(Date)
    checksum: Mapped[str] = mapped_column(String(64), unique=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)


class TelemetryObservation(Base, TimestampMixin):
    __tablename__ = "telemetry_observations"
    __table_args__ = (
        UniqueConstraint(
            "station_id",
            "observed_at",
            "metric",
            "depth_cm",
            name="uq_telemetry_identity",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_telemetry_metric_time", "metric", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    station_id: Mapped[str] = mapped_column(String(96), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    depth_cm: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="conduit")
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    model_version: Mapped[str | None] = mapped_column(String(64))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_source_payloads.id", ondelete="SET NULL")
    )


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    source: Mapped[str] = mapped_column(String(64), default="open-meteo")
    model: Mapped[str] = mapped_column(String(96), default="best_match")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="success")
    units: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    __table_args__ = (
        UniqueConstraint("forecast_run_id", "valid_at", name="uq_forecast_run_valid_at"),
        Index("ix_forecast_point_valid_at", "valid_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), index=True
    )
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity_pct: Mapped[float | None] = mapped_column(Float)
    precipitation_probability_pct: Mapped[float | None] = mapped_column(Float)
    precipitation_mm: Mapped[float | None] = mapped_column(Float)
    uv_index: Mapped[float | None] = mapped_column(Float)
    wind_speed_m_s: Mapped[float | None] = mapped_column(Float)
    wind_gust_m_s: Mapped[float | None] = mapped_column(Float)
    et0_mm: Mapped[float | None] = mapped_column(Float)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    run: Mapped[ForecastRun] = relationship()


class SatelliteScene(Base, TimestampMixin):
    __tablename__ = "satellite_scenes"

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), default="microsoft-planetary-computer")
    collection: Mapped[str] = mapped_column(String(64), default="sentinel-2-l2a")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float)
    processing_status: Mapped[str] = mapped_column(String(32), default="discovered")
    valid_fraction: Mapped[float | None] = mapped_column(Float)
    assets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    footprint: Mapped[Any | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))


class H3Cell(Base, TimestampMixin):
    __tablename__ = "h3_cells"

    h3_index: Mapped[str] = mapped_column(String(16), primary_key=True)
    resolution: Mapped[int] = mapped_column(Integer, index=True)
    area_ha: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    centroid: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    slope_deg: Mapped[float | None] = mapped_column(Float)
    water_distance_m: Mapped[float | None] = mapped_column(Float)
    terrain_source: Mapped[str | None] = mapped_column(String(96))
    water_source: Mapped[str | None] = mapped_column(String(96))


class CellObservation(Base, TimestampMixin):
    __tablename__ = "cell_observations"
    __table_args__ = (
        UniqueConstraint("h3_index", "scene_id", name="uq_cell_scene"),
        Index("ix_cell_observation_time", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    h3_index: Mapped[str] = mapped_column(
        String(16), ForeignKey("h3_cells.h3_index", ondelete="CASCADE"), index=True
    )
    scene_id: Mapped[str] = mapped_column(
        String(180), ForeignKey("satellite_scenes.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ndvi: Mapped[float | None] = mapped_column(Float)
    ndmi: Mapped[float | None] = mapped_column(Float)
    valid_fraction: Mapped[float] = mapped_column(Float, default=0)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    model_version: Mapped[str] = mapped_column(String(64), default="spectral-indices-v1")

    cell: Mapped[H3Cell] = relationship()
    scene: Mapped[SatelliteScene] = relationship()


class WaterPoint(Base, TimestampMixin):
    __tablename__ = "water_points"

    osm_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(180))
    feature_type: Mapped[str] = mapped_column(String(64))
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RouteRun(Base):
    __tablename__ = "route_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="complete")
    start_point: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    end_point: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    total_distance_m: Mapped[float | None] = mapped_column(Float)
    total_time_s: Mapped[float | None] = mapped_column(Float)
    geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    elevation_profile: Mapped[list[dict[str, float]]] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(180))


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    auth_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    default_pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat"
    )
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="SolarShepherd member")
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Nairobi")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system_owner: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Mission(Base, TimestampMixin):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    route_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("route_runs.id", ondelete="SET NULL"), index=True
    )
    herd_tlu: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SampleSubmission(Base, TimestampMixin):
    __tablename__ = "sample_submissions"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "external_reference", name="uq_sample_owner_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    sample_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    external_reference: Mapped[str | None] = mapped_column(String(128))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    dry_matter_kg_ha: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(180))
    quadrat_area_m2: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    review_notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL")
    )
    calibration_sample_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_samples.id", ondelete="SET NULL")
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id", ondelete="SET NULL"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)


class SampleAttachment(Base):
    __tablename__ = "sample_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sample_submissions.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportRun(Base, TimestampMixin):
    __tablename__ = "report_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    pdf_object_key: Mapped[str | None] = mapped_column(String(512))
    json_object_key: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    metric: Mapped[str | None] = mapped_column(String(64))
    comparator: Mapped[str | None] = mapped_column(String(8))
    threshold: Mapped[float | None] = mapped_column(Float)
    lookahead_hours: Mapped[int] = mapped_column(Integer, default=24)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=180)
    channels: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["in_app"])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    response_mode: Mapped[str] = mapped_column(String(24), default="case_and_mission")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResponseCase(Base, TimestampMixin):
    __tablename__ = "response_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="triage", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    dismissal_reason: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rule: Mapped[AlertRule | None] = relationship()
    mission: Mapped[Mission] = relationship()
    alerts: Mapped[list[Alert]] = relationship(back_populates="response_case")
    updates: Mapped[list[ResponseUpdate]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="ResponseUpdate.created_at"
    )


class ResponseUpdate(Base):
    __tablename__ = "response_updates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    response_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("response_cases.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    notes: Mapped[str] = mapped_column(Text)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    case: Mapped[ResponseCase] = relationship(back_populates="updates")
    author: Mapped[UserProfile] = relationship()
    attachments: Mapped[list[ResponseAttachment]] = relationship(
        cascade="all, delete-orphan", order_by="ResponseAttachment.created_at"
    )


class ResponseAttachment(Base):
    __tablename__ = "response_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    update_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("response_updates.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True
    )
    response_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("response_cases.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    response_case: Mapped[ResponseCase | None] = relationship(back_populates="alerts")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    provider_id: Mapped[str | None] = mapped_column(String(180))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(96), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(180))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class DataSourceSetting(Base, TimestampMixin):
    __tablename__ = "data_source_settings"

    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), primary_key=True, default="jkuat"
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule: Mapped[str | None] = mapped_column(String(96))
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL")
    )


class CalibrationSample(Base, TimestampMixin):
    __tablename__ = "calibration_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    external_sample_id: Mapped[str] = mapped_column(String(128), unique=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    dry_matter_kg_ha: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(180))
    quadrat_area_m2: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_imports.id", ondelete="SET NULL"), index=True
    )


class CalibrationImport(Base):
    __tablename__ = "calibration_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pilot_slug: Mapped[str] = mapped_column(
        String(32), ForeignKey("pilots.slug"), default="jkuat", index=True
    )
    checksum: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="success")
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    coefficients: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
