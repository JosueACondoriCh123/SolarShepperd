import asyncio
from app.db import SessionLocal
from app.config import get_settings
from app.services.routing import RoutingService
from app.schemas import RouteRequest, Coordinate

async def main():
    settings = get_settings()
    print("Probando cálculo de ruta con datos reales de terreno...")
    
    # Coordenadas dentro del piloto JKUAT (centro: -1.1018, 37.0144)
    start = Coordinate(latitude=-1.1018, longitude=37.0144)
    end = Coordinate(latitude=-1.0950, longitude=37.0250)
    
    req = RouteRequest(
        start=start,
        end=end,
        max_slope_deg=18.0,
        profile="resource_aware",
        uv_weight=0.6,
        forage_weight=0.25,
        water_weight=0.2,
    )
    
    async with SessionLocal() as session:
        service = RoutingService(session, settings.h3_resolution, "jkuat")
        route = await service.calculate(req)
        print("\n¡RUTA CALCULADA CON ÉXITO!")
        print(f"  ID: {route.id}")
        print(f"  Status: {route.status}")
        print(f"  Distancia: {route.total_distance_m:.1f} m")
        print(f"  Tiempo estimado: {route.estimated_time_s / 60:.1f} min")
        print(f"  Puntos perfil elevación: {len(route.elevation_profile)}")
        print(f"  Quality flags: {route.quality_flags}")
        print(f"  Features GeoJSON: {len(route.geojson.get('features', []))}")
        print(f"  Provenance: {route.diagnostics.get('inputs_as_of')}")

if __name__ == "__main__":
    asyncio.run(main())
