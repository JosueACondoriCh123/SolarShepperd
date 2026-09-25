import asyncio
import time
from app.db import SessionLocal
from app.config import get_settings
from app.services.ingestion import IngestionService

async def main():
    settings = get_settings()
    print("Iniciando ingestión de terreno (Copernicus DEM GLO-30 via Planetary Computer)...")
    
    for pilot_slug in ["jkuat"]:
        print(f"\n==========================================")
        print(f"Ejecutando IngestionService.ingest_terrain() para piloto: {pilot_slug}...")
        t0 = time.time()
        try:
            async with SessionLocal() as session:
                service = IngestionService(session, settings, pilot_slug)
                run = await service.ingest_terrain()
                print(f"Resultado IngestionRun:")
                print(f"  Status: {run.status}")
                print(f"  Records seen: {run.records_seen}")
                print(f"  Records written: {run.records_written}")
                print(f"  Error: {run.error_code} - {run.error_message}")
                print(f"  Diagnostics: {run.diagnostics}")
                print(f"Tiempo total: {time.time()-t0:.2f}s")
        except Exception as e:
            print(f"Error en {pilot_slug}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
