import asyncio
from app.db import SessionLocal
from app.models import (
    IngestionRun,
    TelemetryObservation,
    H3Cell,
    CellObservation,
    WaterPoint,
    CalibrationSample,
    ForecastPoint,
    SatelliteScene,
)
from sqlalchemy import select, func

async def check():
    async with SessionLocal() as s:
        print("=== CONTEOS POR TABLA (BASE DE DATOS SUPABASE) ===")
        models = [
            (TelemetryObservation, "TelemetryObservation (Conduit / GeoCSV / METAR)"),
            (ForecastPoint, "ForecastPoint (Pronósticos Open-Meteo)"),
            (WaterPoint, "WaterPoint (Puntos de agua OSM)"),
            (H3Cell, "H3Cell (Celdas hexagonales/terreno DEM)"),
            (SatelliteScene, "SatelliteScene (Escenas satelitales Sentinel-2)"),
            (CellObservation, "CellObservation (NDVI / NDMI)"),
            (CalibrationSample, "CalibrationSample (Muestras de calibración)"),
        ]
        for model, label in models:
            cnt = (await s.execute(select(func.count()).select_from(model))).scalar()
            print(f"- {label}: {cnt} registros")

        print("\n=== TELEMETRÍA POR PILOTO Y FUENTE ===")
        stmt = (
            select(TelemetryObservation.pilot_slug, TelemetryObservation.source, func.count(TelemetryObservation.id))
            .group_by(TelemetryObservation.pilot_slug, TelemetryObservation.source)
        )
        for pilot, source, count in (await s.execute(stmt)).all():
            print(f"  * Piloto: {pilot:10} | Fuente: {source:16} | Registros: {count}")

        print("\n=== ULTIMAS EJECUCIONES DE INGESTIÓN ===")
        runs = (await s.execute(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(15))).scalars().all()
        for r in runs:
            date_str = r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "N/A"
            err = f" | Error: {r.error_code} - {r.error_message}" if r.error_code or r.error_message else ""
            print(f"  [{date_str}] {r.source:16} | Piloto: {r.pilot_slug:8} | Status: {r.status:12} | Vistos: {r.records_seen:7} | Escritos: {r.records_written:7}{err}")

if __name__ == "__main__":
    asyncio.run(check())
