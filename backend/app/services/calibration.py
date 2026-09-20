from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import h3
from dateutil.parser import isoparse

REQUIRED_SAMPLE_FIELDS = (
    "sample_id",
    "sampled_at_with_timezone",
    "latitude",
    "longitude",
    "dry_matter_kg_ha",
    "method",
    "quadrat_area_m2",
)


@dataclass(frozen=True)
class ValidatedSample:
    sample_id: str
    sampled_at: datetime
    latitude: float
    longitude: float
    dry_matter_kg_ha: float
    method: str
    quadrat_area_m2: float


@dataclass(frozen=True)
class SampleValidation:
    checksum: str
    rows: list[ValidatedSample]
    errors: list[dict[str, Any]]

    @property
    def valid(self) -> bool:
        return not self.errors


def sample_template() -> str:
    return ",".join(REQUIRED_SAMPLE_FIELDS) + "\n"


def _add_error(errors: list[dict[str, Any]], row: int, field: str, message: str) -> None:
    errors.append({"row": row, "field": field, "message": message})


def validate_sample_csv(
    payload: bytes,
    pilot_lat: float,
    pilot_lon: float,
    pilot_radius_km: float,
) -> SampleValidation:
    checksum = hashlib.sha256(payload).hexdigest()
    errors: list[dict[str, Any]] = []
    rows: list[ValidatedSample] = []
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return SampleValidation(
            checksum,
            [],
            [{"row": 0, "field": "file", "message": "CSV must be UTF-8 encoded."}],
        )
    reader = csv.DictReader(io.StringIO(content))
    missing = [field for field in REQUIRED_SAMPLE_FIELDS if field not in (reader.fieldnames or [])]
    if missing:
        return SampleValidation(
            checksum,
            [],
            [
                {"row": 1, "field": field, "message": "Required column is missing."}
                for field in missing
            ],
        )
    seen: set[str] = set()
    for line, raw in enumerate(reader, start=2):
        row_errors: list[dict[str, Any]] = []

        sample_id = (raw.get("sample_id") or "").strip()
        if not sample_id:
            _add_error(row_errors, line, "sample_id", "A sample identifier is required.")
        elif sample_id in seen:
            _add_error(row_errors, line, "sample_id", "Duplicate sample_id in this file.")
        seen.add(sample_id)

        try:
            sampled_at = isoparse((raw.get("sampled_at_with_timezone") or "").strip())
            if sampled_at.tzinfo is None:
                _add_error(
                    row_errors,
                    line,
                    "sampled_at_with_timezone",
                    "An explicit UTC offset or timezone is required.",
                )
        except (TypeError, ValueError):
            sampled_at = datetime.min
            _add_error(
                row_errors,
                line,
                "sampled_at_with_timezone",
                "Use a valid ISO-8601 timestamp with timezone.",
            )

        parsed: dict[str, float] = {}
        for field in ("latitude", "longitude", "dry_matter_kg_ha", "quadrat_area_m2"):
            try:
                value = float(raw.get(field) or "")
                if not math.isfinite(value):
                    raise ValueError
                parsed[field] = value
            except ValueError:
                parsed[field] = 0.0
                _add_error(row_errors, line, field, "A finite numeric value is required.")
        latitude = parsed["latitude"]
        longitude = parsed["longitude"]
        if not -90 <= latitude <= 90:
            _add_error(row_errors, line, "latitude", "Latitude must be between -90 and 90.")
        if not -180 <= longitude <= 180:
            _add_error(row_errors, line, "longitude", "Longitude must be between -180 and 180.")
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            distance_km = h3.great_circle_distance(
                (pilot_lat, pilot_lon), (latitude, longitude), unit="km"
            )
            if distance_km > pilot_radius_km:
                _add_error(
                    row_errors,
                    line,
                    "latitude",
                    f"Sample is outside the {pilot_radius_km:g} km pilot area.",
                )
        if parsed["dry_matter_kg_ha"] <= 0:
            _add_error(
                row_errors,
                line,
                "dry_matter_kg_ha",
                "Dry matter must be greater than zero.",
            )
        if parsed["quadrat_area_m2"] <= 0:
            _add_error(
                row_errors,
                line,
                "quadrat_area_m2",
                "Quadrat area must be greater than zero.",
            )
        method = (raw.get("method") or "").strip()
        if not method:
            _add_error(row_errors, line, "method", "A documented sampling method is required.")

        errors.extend(row_errors)
        if not row_errors:
            rows.append(
                ValidatedSample(
                    sample_id=sample_id,
                    sampled_at=sampled_at,
                    latitude=latitude,
                    longitude=longitude,
                    dry_matter_kg_ha=parsed["dry_matter_kg_ha"],
                    method=method,
                    quadrat_area_m2=parsed["quadrat_area_m2"],
                )
            )
    if not rows and not errors:
        errors.append({"row": 1, "field": "file", "message": "CSV contains no sample rows."})
    return SampleValidation(checksum, rows, errors)
