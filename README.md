# SolarShepherd

SolarShepherd turns real Conduit@Empathy and NOAA Aviation Weather observations,
Sentinel-2 L2A imagery, Copernicus DEM terrain and OpenStreetMap water features
into transparent climate and pastoral decision support for three 10 km Kenya
pilots: JKUAT, Garissa and Lodwar.

The application never fabricates operational measurements. Until local dry
matter samples are available, biomass and grazing-capacity outputs remain
locked and the UI explains the calibration requirements.

## Run locally

1. Copy `.env.example` to `.env`.
2. Set a **rotated** `CONDUIT_API_KEY`, the registered `CONDUIT_EMAIL`, and a
   long `API_ADMIN_TOKEN`. Never commit this file.
3. Start the system:

   ```bash
   docker compose up --build
   ```

4. Open `http://localhost:5173`. API documentation is available at
   `http://localhost:8000/docs`.

Local development uses a deterministic owner session so the complete product
can be exercised without cloud credentials. Choose **Explore as guest** on the
landing page to verify the read-only experience. This shortcut is rejected when
`ENVIRONMENT=production`; production refuses to start unless Supabase Auth is
configured.

The product routes are:

- Public: landing, login, signup, recovery, email verification, privacy and
  terms.
- Observe: Dashboard, Telemetry and Landscape.
- Plan: Route Planner and Missions.
- Evidence: Samples, Carrying Capacity and Reports.
- Manage: Alerts, Team, Data Sources, Operations and Settings.

Authenticated routes use `/app/:pilotSlug/*`, where `pilotSlug` is `jkuat`,
`garissa` or `lodwar`. The pilot selector preserves the current section and the
last valid choice. Legacy `/app/*` links redirect to the saved pilot, while an
unknown slug returns to JKUAT with an explicit notice.

Members can only access their own missions, route exports, samples, reports and
alert rules. The verified addresses in `SYSTEM_OWNER_EMAILS` can review samples,
manage members and operate sources. Guests can inspect shared pilot science and
request a demonstration route, but cannot save, export or submit anything.

The first Conduit response is stored intact and inspected without guessing its
schema. Configure `CONDUIT_FIELD_MAP_JSON` after reviewing the discovered field
paths shown in Operations. Example:

```json
{
  "observed_at": "ts",
  "temperature_c": "st1",
  "relative_humidity_pct": "sh1",
  "pressure_hpa": "bp1",
  "precipitation_mm": "rgt",
  "wind_speed_m_s": "ws",
  "wind_direction_deg": "wd",
  "wind_gust_m_s": "wg"
}
```

Trigger a protected ingestion from a terminal:

```bash
curl -X POST http://localhost:8000/api/v1/admin/ingestions/conduit/run \
  -H "X-Admin-Token: $API_ADMIN_TOKEN"
```

Supported sources are `conduit`, `aviation_weather`, `forecast`, `satellite`,
`terrain`, and `osm`. Conduit remains specific to JKUAT; Garissa and Lodwar use
public METAR observations with exact station provenance and no invented local
station values.

Historical JKUAT FEWSNET GeoCSV exports can be loaded without enabling a live
Conduit credential:

```bash
docker cp jkuat.csv solarshepherd-api-1:/tmp/jkuat.csv
docker compose exec api python -m app.cli import-geocsv /tmp/jkuat.csv
```

The importer verifies the JKUAT site coordinates, stores the file checksum and
metadata, and upserts observations idempotently. It intentionally excludes
battery voltage, the undecoded health bitfield, the unconfirmed second rain
gauge, raw SI1145 UV counts and the defective gust-direction export. Observed
ET₀ remains unavailable until explicit daily Tmin/Tmax inputs are supplied.

Open-Meteo forecasts are stored independently from Conduit observations and are
labelled `FORECAST_NOT_OBSERVATION`. The worker refreshes the 72-hour outlook
every three hours. The free endpoint is suitable for this non-commercial
research demo and requires attribution; commercial deployments must configure a
compatible Open-Meteo plan.

Download the dry-matter CSV contract from
`GET /api/v1/calibration/samples/template.csv`. Validate a completed file before
its atomic import:

```bash
curl -X POST http://localhost:8000/api/v1/admin/calibration/samples/validate \
  -H "X-Admin-Token: $API_ADMIN_TOKEN" -F "file=@samples.csv"
curl -X POST http://localhost:8000/api/v1/admin/calibration/samples/import \
  -H "X-Admin-Token: $API_ADMIN_TOKEN" -F "file=@samples.csv"
```

Imported samples improve the readiness and coverage display only. They do not
activate biomass or grazing-capacity estimates.

## Deployment

### Vercel

Create a Vercel project with `frontend` as the root directory. Set:

- `VITE_API_BASE_URL=https://<api-domain>.up.railway.app/api/v1`
- `VITE_AUTH_MODE=supabase`
- `VITE_SUPABASE_URL=https://<project-ref>.supabase.co`
- `VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>`
- `VITE_TURNSTILE_SITE_KEY=<site-key>`

Only the Supabase URL, publishable key and Turnstile site key belong in Vite.
Never expose the Supabase secret key, Resend key, Conduit credentials or admin
token through a `VITE_` variable.

### Supabase

SolarShepherd uses Supabase for identity and private object storage only;
Railway/PostGIS remains the scientific and operational source of truth.

1. Enable email/password and anonymous sign-ins in Auth.
2. Require email confirmation and configure the application URL plus allowed
   redirect URLs for Vercel previews and production.
3. Enable Cloudflare Turnstile in the Supabase CAPTCHA settings. Store its
   secret in Supabase and publish only the site key to the frontend.
4. Configure Resend as custom SMTP for confirmation and recovery mail.
5. Keep the signing setup asymmetric so FastAPI can validate tokens through the
   project's JWKS endpoint. Tokens are checked for signature, issuer, audience,
   expiry and subject; `is_anonymous` is checked independently of the PostgreSQL
   role.
6. Supply a Supabase secret key to Railway. The API creates and uses the private
   `sample-evidence` and `reports` buckets and issues short-lived signed URLs.

Do not create parallel user or scientific tables in Supabase. `user_profiles`,
missions, samples, reports, alerts and audit events are stored by the Railway
PostGIS service and keyed by the Supabase subject.

### Railway

Create one Railway project with four services:

- `api`: build from `backend/Dockerfile`; start command is defined in
  `backend/railway.toml`.
- `worker`: same image, start command
  `celery -A app.tasks.celery_app:celery_app worker --beat --loglevel=INFO`.
- `redis`: Railway Redis service, private networking only.
- `db`: `postgis/postgis:16-3.4` with a persistent volume mounted at
  `/var/lib/postgresql/data`, private networking only.

Set `ENVIRONMENT=production`, `AUTH_MODE=supabase`, `DATABASE_URL`, `REDIS_URL`,
`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`,
`SYSTEM_OWNER_EMAILS`, `RESEND_API_KEY`, `EMAIL_FROM`, `CONDUIT_API_KEY`,
`CONDUIT_EMAIL`, `API_ADMIN_TOKEN`, and
`CORS_ORIGINS=https://<vercel-domain>`. Run `alembic upgrade head` as the API
pre-deploy command. Keep the database, Redis and worker on Railway's private
network; publish only the API. Mount a persistent volume for PostGIS and another
at `/data/operational` for the local object-storage fallback. Backups remain the
operator's responsibility for the containerized PostGIS database.

After deployment, set the repository variable `SMOKE_API_URL` to the public API
origin. CI will exercise `/health/ready` without embedding credentials.

## Operational workflows

- Missions use optimistic revisions. A stale edit returns a conflict instead of
  silently overwriting field work.
- Sample submissions begin as drafts, are submitted for review and only an owner
  can atomically promote an approved record into calibration samples. JPEG, PNG
  and WebP evidence is re-encoded, stripped of unnecessary metadata, limited to
  8 MB and capped at three files per sample.
- Reports are generated by Celery and stored as private PDF and JSON evidence.
  They snapshot route, weather, landscape and approved sample provenance while
  retaining `CALIBRATION_REQUIRED` for biomass and GCH.
- Alert rules support explicit thresholds for temperature, precipitation,
  probability of rain, UV, wind and gusts, plus stale-data, mission and review
  events. Delivery is idempotent, cooled down, retried and audited.
- Team and data-source management require a system owner. The legacy
  `X-Admin-Token` remains available for CLI ingestion only.

## Scientific behavior

- Hargreaves-Samani ET0 is calculated only when real daily minimum and maximum
  temperatures exist. Extraterrestrial radiation comes from latitude and day
  of year, not a measured-radiation substitute.
- Sentinel-2 NDVI uses B08/B04. Vegetation moisture is correctly named NDMI and
  uses B08/B11. SCL classes mask clouds, shadows, snow, saturation and no-data.
- H3 resolution 9 is used for each configured pilot cost surface. Every route,
  observation, mission, sample, report and alert is isolated by `pilot_slug`.
- A* edge weights are strictly positive travel times adjusted by bounded risk
  multipliers. Missing water or vegetation data has a neutral effect and is
  reported in route quality flags.
- Biomass and GCH are unavailable until a validated calibration model is
  activated.
- Forecast values never fill gaps in observed telemetry and are not used in
  route costs.
- `fastest` routes use terrain travel time only. `resource_aware` routes apply
  the documented bounded environmental weights and export a scientific JSON
  receipt alongside GPX.

## Readiness and offline behavior

- `/health/live` reports the API process.
- `/health/ready` checks PostGIS, Redis and the Celery worker heartbeat.
- The production frontend installs a read-only service worker. Previously read
  telemetry, forecasts, scenes, cells and calibration status remain viewable
  offline. Private profiles, routes, missions, samples, reports and team data are
  never cached by URL.
- Offline sample drafts live in IndexedDB namespaces separated by user. Logout
  is blocked until the user synchronizes, exports or explicitly discards pending
  drafts. New routes are unavailable offline.

## Verification

Run the same gates used by CI:

```bash
.venv/Scripts/ruff check backend
.venv/Scripts/python -m pytest -q backend/tests
cd frontend
pnpm lint
pnpm build
pnpm test
pnpm test:e2e
```

The automated suite covers the scientific calculations, ingestion idempotency,
route constraints, JWT rejection paths, anonymous/member separation, operational
schema validation, PDF guardrails and all public/product screens in desktop and
mobile Chromium.
