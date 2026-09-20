from app.services.calibration import sample_template, validate_sample_csv


def test_sample_template_matches_contract() -> None:
    assert sample_template().startswith("sample_id,sampled_at_with_timezone")
    assert "dry_matter_kg_ha" in sample_template()


def test_valid_sample_requires_timezone_and_pilot_location() -> None:
    payload = (
        b"sample_id,sampled_at_with_timezone,latitude,longitude,dry_matter_kg_ha,method,quadrat_area_m2\n"
        b"S-01,2026-09-19T12:00:00+03:00,-1.1018,37.0144,850,clipped quadrat,0.25\n"
    )
    result = validate_sample_csv(payload, -1.1018, 37.0144, 10)
    assert result.valid
    assert result.rows[0].sample_id == "S-01"
    assert result.rows[0].dry_matter_kg_ha == 850


def test_invalid_batch_reports_all_scientific_contract_errors() -> None:
    payload = (
        b"sample_id,sampled_at_with_timezone,latitude,longitude,dry_matter_kg_ha,method,quadrat_area_m2\n"
        b"S-01,2026-09-19T12:00:00,-2,39,-1,,0\n"
    )
    result = validate_sample_csv(payload, -1.1018, 37.0144, 10)
    fields = {error["field"] for error in result.errors}
    assert "sampled_at_with_timezone" in fields
    assert "latitude" in fields
    assert "dry_matter_kg_ha" in fields
    assert "method" in fields
    assert "quadrat_area_m2" in fields
