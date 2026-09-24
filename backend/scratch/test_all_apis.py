import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, UTC
import httpx
from dotenv import load_dotenv

# Load backend/.env
backend_env_path = r"c:\Users\HP\Documents\A hack the weather\backend\.env"
load_dotenv(backend_env_path)

print("=" * 60)
print("TESTING ALL EXTERNAL APIS & INTEGRATIONS")
print("=" * 60)

async def test_conduit():
    print("\n--- 1. TESTING CONDUIT API ---")
    url = os.getenv("CONDUIT_API_URL", "https://conduit.jhubafrica.com/data.php")
    api_key = os.getenv("CONDUIT_API_KEY", "")
    email = os.getenv("CONDUIT_EMAIL", "")
    print(f"URL: {url}")
    print(f"API Key: {api_key[:4]}...{api_key[-4:] if len(api_key)>8 else ''}")
    print(f"Email: {email}")

    today = date.today()
    from_date = (today - timedelta(days=7)).isoformat()
    to_date = today.isoformat()

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.post(
                url,
                data={
                    "apikey": api_key,
                    "email": email,
                    "fromdate": from_date,
                    "todate": to_date,
                },
                headers={"Accept": "application/json", "User-Agent": "SolarShepherd/0.1"},
            )
            print(f"Status Code: {resp.status_code}")
            print(f"Response Headers: {dict(resp.headers)}")
            print(f"Response Text (first 500 chars): {resp.text[:500]}")
            try:
                data = resp.json()
                print(f"JSON parsed successfully! Type: {type(data)}")
                if isinstance(data, list):
                    print(f"Records count: {len(data)}")
                    if data:
                        print(f"First record sample: {json.dumps(data[0])[:200]}")
                elif isinstance(data, dict):
                    print(f"Dict keys: {list(data.keys())}")
                    print(f"Dict sample: {json.dumps(data)[:200]}")
            except Exception as e:
                print(f"Failed to parse JSON: {e}")
    except Exception as e:
        print(f"Conduit request error: {type(e).__name__}: {e}")

async def test_open_meteo():
    print("\n--- 2. TESTING OPEN-METEO API ---")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": -1.1018,
        "longitude": 37.0144,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,uv_index,wind_speed_10m,wind_gusts_10m,et0_fao_evapotranspiration",
        "forecast_hours": 24,
        "timezone": "UTC",
        "wind_speed_unit": "ms",
        "models": "best_match",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            print(f"Status Code: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                hourly = data.get("hourly", {})
                times = hourly.get("time", [])
                print(f"Forecast hours returned: {len(times)}")
                print(f"Hourly keys: {list(hourly.keys())}")
            else:
                print(f"Response: {resp.text[:300]}")
    except Exception as e:
        print(f"Open-Meteo request error: {e}")

async def test_aviation_weather():
    print("\n--- 3. TESTING NOAA AVIATION WEATHER METAR ---")
    url = "https://aviationweather.gov/api/data/metar"
    params = {"ids": "HKJK,HKGA,HKLO", "format": "json", "hours": 24}
    headers = {"User-Agent": "SolarShepherd/0.2 scientific-pilot"}
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            resp = await client.get(url, params=params)
            print(f"Status Code: {resp.status_code}")
            if resp.status_code in (200, 204):
                if resp.status_code == 204:
                    print("Status 204: No METAR content returned for stations")
                else:
                    data = resp.json()
                    print(f"Returned {len(data)} METAR reports.")
                    if data:
                        print(f"Sample station: {data[0].get('icaoId')}, temp: {data[0].get('temp')}, dewp: {data[0].get('dewp')}")
            else:
                print(f"Response: {resp.text[:300]}")
    except Exception as e:
        print(f"Aviation Weather error: {e}")

async def test_osm():
    print("\n--- 4. TESTING OPENSTREETMAP OVERPASS API ---")
    urls = [
        os.getenv("OSM_OVERPASS_URL", "https://lz4.overpass-api.de/api/interpreter"),
        "https://overpass-api.de/api/interpreter",
    ]
    bbox = "-1.1918,36.9244,-1.0118,37.1044"
    query = f"""
    [out:json][timeout:30];
    (
      nwr["amenity"="drinking_water"]({bbox});
      nwr["amenity"="watering_place"]({bbox});
      nwr["waterway"="water_point"]({bbox});
      nwr["natural"="spring"]({bbox});
      nwr["natural"="water"]({bbox});
    );
    out center tags;
    """
    for endpoint in urls:
        print(f"Trying endpoint: {endpoint}")
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": "SolarShepherd/0.1 (research prototype)"},
                )
                print(f"  Status Code: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    elements = data.get("elements", [])
                    print(f"  Success! Elements found: {len(elements)}")
                    break
                else:
                    print(f"  Failed with status {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  Endpoint error: {type(e).__name__}: {e}")

async def test_supabase_storage():
    print("\n--- 5. TESTING SUPABASE STORAGE API ---")
    supabase_url = os.getenv("SUPABASE_URL", "")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "")
    print(f"Supabase URL: {supabase_url}")
    print(f"Secret key present: {bool(secret_key)}")

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "apikey": secret_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{supabase_url.rstrip('/')}/storage/v1/bucket", headers=headers)
            print(f"Bucket list status: {resp.status_code}")
            if resp.status_code == 200:
                buckets = resp.json()
                print(f"Buckets: {[b.get('name') for b in buckets]}")
            else:
                print(f"Bucket list response: {resp.text[:200]}")
    except Exception as e:
        print(f"Supabase storage error: {e}")

async def test_planetary_computer():
    print("\n--- 6. TESTING PLANETARY COMPUTER STAC API ---")
    try:
        from pystac_client import Client
        import planetary_computer
        from shapely.geometry import Point, mapping

        STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
        catalog = Client.open(STAC_URL)
        area = Point(37.0144, -1.1018).buffer(0.09)
        end = datetime.now(UTC)
        start = end - timedelta(days=60)

        print("Searching Sentinel-2 scenes...")
        search = catalog.search(
            collections=["sentinel-2-l2a"],
            intersects=mapping(area),
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lte": 40}},
            sortby=[{"field": "properties.datetime", "direction": "desc"}],
            max_items=3,
        )
        items = list(search.items())
        print(f"Found {len(items)} Sentinel items.")
        if items:
            item = items[0]
            print(f"Latest item ID: {item.id}, acquired: {item.datetime}")
            print(f"Assets: {list(item.assets.keys())[:10]}")
            signed = planetary_computer.sign(item)
            b04 = signed.assets.get("B04")
            print(f"Signed B04 URL: {b04.href[:100]}...")

            # Test a quick HEAD or GET request on the signed asset href
            async with httpx.AsyncClient(timeout=10) as client:
                head_resp = await client.head(b04.href)
                print(f"Signed asset HEAD status: {head_resp.status_code}")

        print("\nSearching Copernicus DEM scenes...")
        dem_search = catalog.search(
            collections=["cop-dem-glo-30"],
            intersects=mapping(area),
            max_items=3,
        )
        dem_items = list(dem_search.items())
        print(f"Found {len(dem_items)} DEM items.")
        if dem_items:
            dem_item = dem_items[0]
            print(f"DEM item ID: {dem_item.id}")
            signed_dem = planetary_computer.sign(dem_item)
            data_asset = signed_dem.assets.get("data")
            if data_asset:
                print(f"Signed DEM data URL: {data_asset.href[:100]}...")
                async with httpx.AsyncClient(timeout=10) as client:
                    dem_resp = await client.head(data_asset.href)
                    print(f"Signed DEM asset HEAD status: {dem_resp.status_code}")
    except Exception as e:
        print(f"Planetary computer error: {type(e).__name__}: {e}")

async def main():
    await test_conduit()
    await test_open_meteo()
    await test_aviation_weather()
    await test_osm()
    await test_supabase_storage()
    await test_planetary_computer()

if __name__ == "__main__":
    asyncio.run(main())
