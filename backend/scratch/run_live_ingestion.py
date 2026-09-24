import asyncio
import time
from app.db import SessionLocal
from app.config import get_settings
from app.services.ingestion import IngestionService

async def main():
    settings = get_settings()
    print("=== LIVE INGESTION TEST ===", flush=True)

    # 1. Forecast Ingestion
    print("\n1. Running Open-Meteo ingest_forecast...", flush=True)
    t0 = time.time()
    async with SessionLocal() as session:
        service = IngestionService(session, settings, "jkuat")
        run = await service.ingest_forecast()
        print(f"Forecast finished in {time.time()-t0:.2f}s! Status: {run.status}, Seen: {run.records_seen}, Written: {run.records_written}, Error: {run.error_message}", flush=True)

    # 2. Aviation Weather Ingestion
    print("\n2. Running Aviation Weather ingest_public_observations...", flush=True)
    t0 = time.time()
    async with SessionLocal() as session:
        service = IngestionService(session, settings, "jkuat")
        run = await service.ingest_public_observations(hours=24)
        print(f"Aviation Weather finished in {time.time()-t0:.2f}s! Status: {run.status}, Seen: {run.records_seen}, Written: {run.records_written}, Error: {run.error_message}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
