from app.services.reporting import _render_pdf


def test_report_pdf_preserves_calibration_guardrail() -> None:
    manifest = {
        "mission": {
            "title": "North paddock survey",
            "status": "completed",
            "scheduled_start": "2026-09-19T08:00:00+03:00",
            "scheduled_end": "2026-09-19T10:00:00+03:00",
        },
        "route": {"distance_m": 1300.0},
        "sources": {
            "telemetry_latest_at": "2026-09-19T07:55:00Z",
            "forecast_run_id": "forecast-1",
            "sentinel_scene_id": "scene-1",
        },
        "approved_samples": [],
        "scientific_guardrails": {
            "biomass": "CALIBRATION_REQUIRED",
            "gch": "CALIBRATION_REQUIRED",
            "forecast_used_in_route_cost": False,
        },
    }

    pdf = _render_pdf(manifest)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1_000
