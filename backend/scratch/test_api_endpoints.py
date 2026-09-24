import asyncio
from httpx import AsyncClient, ASGITransport
from dotenv import load_dotenv

load_dotenv(r"c:\Users\HP\Documents\A hack the weather\backend\.env")

from app.main import app

async def test_admin_ingestions():
    transport = ASGITransport(app=app)
    headers = {
        "X-Admin-Token": "local-development-change-me",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        print("1. Testing GET /api/v1/admin/data-sources...")
        res = await client.get("/api/v1/admin/data-sources", headers=headers)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            for s in res.json().get("data", []):
                print(f"  Source: {s['source']} | Status: {s['latest_status']} | Records: {s['records_written']} | Run at: {s['latest_run_at']}")
        else:
            print("Response:", res.text)

        print("\n2. Testing POST /api/v1/admin/ingestions/forecast/run (auto/sync)...")
        res = await client.post("/api/v1/admin/ingestions/forecast/run?pilot=jkuat", headers=headers)
        print(f"Forecast Run Status: {res.status_code}")
        print("Response:", res.json())

        print("\n3. Testing POST /api/v1/admin/ingestions/conduit/run (auto/sync)...")
        res = await client.post("/api/v1/admin/ingestions/conduit/run?pilot=jkuat", headers=headers)
        print(f"Conduit Run Status: {res.status_code}")
        print("Response:", res.json())

if __name__ == "__main__":
    asyncio.run(test_admin_ingestions())
