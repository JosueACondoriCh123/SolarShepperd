from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal, engine
from app.services.ingestion import IngestionService


async def _import_geocsv(paths: list[Path]) -> int:
    settings = get_settings()
    try:
        async with SessionLocal() as session:
            service = IngestionService(session, settings, "jkuat")
            removed = await service.remove_unverified_jkuat_observations()
            results = []
            for path in paths:
                run = await service.ingest_geocsv(path)
                results.append(
                    {
                        "run_id": str(run.id),
                        "filename": path.name,
                        "status": run.status,
                        "records_seen": run.records_seen,
                        "records_written": run.records_written,
                        "error_code": run.error_code,
                    }
                )
            print(
                json.dumps(
                    {
                        "pilot_slug": "jkuat",
                        "unverified_observations_removed": removed,
                        "imports": results,
                    }
                )
            )
            return 0 if all(item["status"] == "success" for item in results) else 1
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="SolarShepherd operational commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser(
        "import-geocsv", description="Import verified JKUAT FEWSNET GeoCSV observations"
    )
    import_parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "import-geocsv":
        missing = [str(path) for path in args.paths if not path.is_file()]
        if missing:
            parser.error(f"files not found: {', '.join(missing)}")
        return asyncio.run(_import_geocsv(args.paths))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
