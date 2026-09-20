from app.integrations.conduit import discover_field_paths, normalize_records


def test_discovery_reports_paths_without_guessing_meanings() -> None:
    payload = {"records": [{"time": "2026-09-01T10:00:00Z", "sensor": {"a": 12}}]}
    assert discover_field_paths(payload) == ["records.sensor.a", "records.time"]


def test_normalization_requires_explicit_field_map() -> None:
    payload = [{"timestamp": "2026-09-01T10:00:00Z", "temperature": 24.5}]
    assert normalize_records(payload, {}, "station") == []


def test_normalization_uses_canonical_units() -> None:
    payload = [{"timestamp": "2026-09-01T10:00:00Z", "temperature": "24.5"}]
    records = normalize_records(
        payload,
        {"observed_at": "timestamp", "temperature_c": "temperature"},
        "station",
    )
    assert records[0]["value"] == 24.5
    assert records[0]["unit"] == "°C"
    assert records[0]["metric"] == "temperature_c"
