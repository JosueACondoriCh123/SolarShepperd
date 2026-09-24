import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv(r"c:\Users\HP\Documents\A hack the weather\backend\.env")

from app.db import SessionLocal
from app.config import get_settings
from app.services.ingestion import IngestionService

async def test_all_ingestions():
    settings = get_settings()
    print("Testing Ingestions directly with database...")

    # 1. Forecast (Open-Meteo)
    print("\n--- Testing Open-Meteo Forecast Ingestion ---")
    try:
        async with SessionLocal() as session:
            service = IngestionService(session, settings, "jkuat")
            run = await service.ingest_forecast()
            print(f"Forecast Ingestion Run status: {run.status}, records_written: {run.records_written}, error: {run.error_message}")
    except Exception as e:
        print(f"Forecast Ingestion Exception: {type(e).__name__}: {e}")

    # 2. Aviation Weather METAR
    print("\n--- Testing Aviation Weather METAR Ingestion ---")
    try:
        async with SessionLocal() as session:
            service = IngestionService(session, settings, "jkuat")
            run = await service.ingest_public_observations(hours=24)
            print(f"Aviation Weather Ingestion Run status: {run.status}, records_written: {run.records_written}, error: {run.error_message}")
    except Exception as e:
        print(f"Aviation Weather Exception: {type(e).__name__}: {e}")

    # 3. OSM Overpass
    print("\n--- Testing OSM Water Features Ingestion ---")
    try:
        # Note: update settings.osm_overpass_url if it failed before
        async with SessionLocal() as session:
            service = IngestionService(session, settings, "jkuat")
            run = await service.ingest_osm()
            print(f"OSM Ingestion Run status: {run.status}, records_written: {run.records_written}, error: {run.error_message}")
    except Exception as e:
        print(f"OSM Ingestion Exception: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_all_ingestions())
