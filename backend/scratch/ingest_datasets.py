import asyncio
import time
from pathlib import Path
from app.db import SessionLocal
from app.config import get_settings
from app.services.ingestion import IngestionService

async def main():
    settings = get_settings()
    data_dir = Path("data")
    
    files = [
        data_dir / "3DFEWSNET_SiteJKUAT_KenyaKiambuJKUATIOTAWS-Conduti@Empathy1.csv",
        data_dir / "3DFEWSNET_SiteJKUAT_KenyaKiambuJKUATIOTAWS-Conduti@Empathy11-15.csv",
    ]
    
    for f in files:
        if not f.exists():
            print(f"File not found: {f}", flush=True)
            continue
        print(f"\n==================================================", flush=True)
        print(f"Starting ingestion for: {f.name}", flush=True)
        t0 = time.time()
        async with SessionLocal() as session:
            service = IngestionService(session, settings, "jkuat")
            run = await service.ingest_geocsv(f)
            elapsed = time.time() - t0
            print(f"Finished {f.name} in {elapsed:.1f}s", flush=True)
            print(f"Status: {run.status}", flush=True)
            print(f"Records seen: {run.records_seen}", flush=True)
            print(f"Records written: {run.records_written}", flush=True)
            if run.error_message:
                print(f"Error: {run.error_message}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
