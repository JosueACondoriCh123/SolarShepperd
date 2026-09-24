import asyncio
import time
from datetime import UTC, datetime, timedelta
from app.db import SessionLocal
from app.config import get_settings
from app.services.ingestion import IngestionService
from app.pilots import get_pilot
from app.integrations.satellite import (
    search_latest_sentinel_scene,
    SENTINEL_COLLECTION,
)

async def test_satellite_for_pilot(pilot_slug: str):
    settings = get_settings()
    pilot = get_pilot(pilot_slug)
    print(f"\n==========================================")
    print(f"Buscando escena Sentinel-2 para piloto: {pilot.name} ({pilot_slug})")
    
    end = datetime.now(UTC)
    start = end - timedelta(days=settings.stac_lookback_days)
    print(f"Ventana de tiempo: {start.strftime('%Y-%m-%d')} a {end.strftime('%Y-%m-%d')}")
    print(f"Filtro nubes max: {settings.stac_max_cloud_percent}%")

    t0 = time.time()
    try:
        item = await asyncio.to_thread(
            search_latest_sentinel_scene,
            pilot.boundary,
            start,
            end,
            settings.stac_max_cloud_percent,
        )
        if item is None:
            print(f"AVISO: No se encontró escena con <= {settings.stac_max_cloud_percent}% nubes en los últimos {settings.stac_lookback_days} días.")
            print(f"Probando ampliar la ventana a 120 días y nubes a 50%...")
            start_extended = end - timedelta(days=120)
            item = await asyncio.to_thread(
                search_latest_sentinel_scene,
                pilot.boundary,
                start_extended,
                end,
                50.0,
            )
            if item is None:
                print(f"ERROR: Aún no se encontró ninguna escena en Planetary Computer.")
                return None
            else:
                print(f"Escena encontrada con parámetros extendidos: {item.id}")
        else:
            print(f"Escena encontrada: {item.id} (Adquirida: {item.datetime}, Nubes: {item.properties.get('eo:cloud_cover')}%)")
            
        print(f"Tiempo de búsqueda STAC: {time.time()-t0:.2f}s")

        print(f"\nEjecutando IngestionService.ingest_satellite() para {pilot_slug}...")
        t1 = time.time()
        async with SessionLocal() as session:
            service = IngestionService(session, settings, pilot_slug)
            run = await service.ingest_satellite()
            print(f"Resultado IngestionRun:")
            print(f"  Status: {run.status}")
            print(f"  Records seen: {run.records_seen}")
            print(f"  Records written: {run.records_written}")
            print(f"  Error: {run.error_code} - {run.error_message}")
            print(f"  Diagnostics: {run.diagnostics}")
            print(f"Tiempo total: {time.time()-t1:.2f}s")
            return run
    except Exception as e:
        print(f"Excepción durante ingest_satellite: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    print("Iniciando ingestión satelital (Sentinel-2 L2A via Microsoft Planetary Computer)...")
    # Comenzar con JKUAT
    await test_satellite_for_pilot("jkuat")

if __name__ == "__main__":
    asyncio.run(main())
