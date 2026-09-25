import asyncio
from app.db import SessionLocal
from sqlalchemy import text

async def check():
    async with SessionLocal() as s:
        res = await s.execute(text("SELECT count(elevation_m) FROM h3_cells"))
        print(f"with_elev: {res.scalar()}")
        run = await s.execute(text("SELECT status, records_written, error_message FROM ingestion_runs WHERE source = 'terrain' ORDER BY started_at DESC LIMIT 1"))
        first = run.mappings().first()
        print(f"latest terrain run: {dict(first) if first else None}")

asyncio.run(check())
