from app.config import Settings


def test_comma_separated_cors_origins_are_parsed(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example, https://preview.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://app.example", "https://preview.example"]


def test_conduit_field_map_remains_explicit_json(monkeypatch) -> None:
    monkeypatch.setenv(
        "CONDUIT_FIELD_MAP_JSON",
        '{"observed_at":"timestamp","temperature_c":"temperature"}',
    )

    settings = Settings(_env_file=None)

    assert settings.conduit_field_map == {
        "observed_at": "timestamp",
        "temperature_c": "temperature",
    }
