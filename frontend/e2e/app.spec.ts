import { expect, test, type Page, type Route } from "@playwright/test";

const emptyCells = {
  type: "FeatureCollection",
  features: [],
  meta: { layer: "ndvi", count: 0, biomass_calibrated: false },
};

const pilots = [
  { slug: "jkuat", name: "JKUAT", center: { latitude: -1.1018, longitude: 37.0144 }, radius_km: 10, timezone: "Africa/Nairobi", bbox: [36.9244, -1.1918, 37.1044, -1.0118], observation_sources: ["Conduit", "NOAA Aviation Weather METAR"], latest_observed_at: "2026-09-19T09:00:00Z", observation_status: "healthy" },
  { slug: "garissa", name: "Garissa", center: { latitude: -0.4635, longitude: 39.6483 }, radius_km: 10, timezone: "Africa/Nairobi", bbox: [39.5583, -0.5535, 39.7383, -0.3735], observation_sources: ["NOAA Aviation Weather METAR"], latest_observed_at: "2026-09-19T09:00:00Z", observation_status: "healthy" },
  { slug: "lodwar", name: "Lodwar", center: { latitude: 3.122, longitude: 35.6087 }, radius_km: 10, timezone: "Africa/Nairobi", bbox: [35.5187, 3.032, 35.6987, 3.212], observation_sources: ["NOAA Aviation Weather METAR"], latest_observed_at: null, observation_status: "never_run" },
].map((pilot) => ({
  ...pilot,
  boundary: {
    type: "Polygon",
    coordinates: [[[pilot.bbox[0], pilot.bbox[1]], [pilot.bbox[2], pilot.bbox[1]], [pilot.bbox[2], pilot.bbox[3]], [pilot.bbox[0], pilot.bbox[3]], [pilot.bbox[0], pilot.bbox[1]]]],
  },
}));

async function mockOperationalApi(page: Page) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/pilots")) {
      await route.fulfill({ json: { data: pilots, count: pilots.length, default_pilot_slug: "jkuat" } });
      return;
    }
    if (/\/pilots\/[^/]+\/context$/.test(path)) {
      const slug = path.split("/").at(-2)!;
      const pilot = pilots.find((item) => item.slug === slug)!;
      await route.fulfill({ json: {
        pilot,
        boundary: { type: "Feature", properties: { pilot_slug: slug, radius_km: 10 }, geometry: pilot.boundary },
        stations: { type: "FeatureCollection", features: [{ type: "Feature", id: `station-${slug}`, geometry: { type: "Point", coordinates: [pilot.center.longitude, pilot.center.latitude] }, properties: { station_id: `station-${slug}`, name: `${pilot.name} station`, source: "NOAA Aviation Weather METAR", role: "primary", distance_to_center_m: 0, outside_pilot: false, latest_observed_at: pilot.latest_observed_at } }] },
        water: { type: "FeatureCollection", features: [] },
        water_coverage_warning: "OpenStreetMap water-feature coverage may be incomplete.",
      } });
      return;
    }
    if (/\/pilots\/[^/]+\/scenes\/[^/]+\/tiles$/.test(path)) {
      const slug = path.split("/").at(-4)!;
      await route.fulfill({ json: { scene_id: "scene-new", pilot_slug: slug, tilejson_url: `https://tiles.example.test/${slug}.json`, source: "planetary-computer", acquired_at: "2026-09-18T08:00:00Z", attribution: "Sentinel-2 L2A via Microsoft Planetary Computer" } });
      return;
    }
    if (path.endsWith("/me")) {
      await route.fulfill({ json: { id: "00000000-0000-4000-8000-000000000001", email: "owner@example.test", display_name: "Pilot owner", timezone: "Africa/Nairobi", status: "active", role: "member", is_system_owner: true, onboarding_completed: true, notification_preferences: { email: true }, default_pilot_slug: "jkuat", created_at: "2026-09-01T00:00:00Z", last_seen_at: "2026-09-19T10:00:00Z" } });
      return;
    }
    if (path.endsWith("/dashboard")) {
      await route.fulfill({ json: { generated_at: "2026-09-19T10:00:00Z", telemetry_latest_at: "2026-09-19T09:00:00Z", forecast_generated_at: "2026-09-19T09:00:00Z", forecast_valid_to: "2026-09-22T09:00:00Z", scene: { id: "scene-new", acquired_at: "2026-09-18T08:00:00Z", cloud_cover_pct: 8 }, active_mission: null, pending_samples: 0, unread_alerts: 0, calibration_status: "CALIBRATION_REQUIRED" } });
      return;
    }
    if (path.endsWith("/missions")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/sample-submissions")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/reports")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/alerts") || path.endsWith("/alert-rules")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/response-cases")) {
      await route.fulfill({
        json: {
          data: [
            {
              id: "33333333-3333-4333-8333-333333333333",
              pilot_slug: "jkuat",
              owner_user_id: "00000000-0000-4000-8000-000000000001",
              rule_id: "44444444-4444-4444-8444-444444444444",
              rule_name: "High Temperature Critical",
              mission_id: "55555555-5555-4555-8555-555555555555",
              mission_title: "Response Mission: High Temperature Critical",
              mission_status: "planned",
              status: "triage",
              severity: "critical",
              revision: 1,
              resolution_notes: null,
              dismissal_reason: null,
              acknowledged_at: null,
              started_at: null,
              completed_at: null,
              closed_at: null,
              dismissed_at: null,
              alert_count: 1,
              update_count: 0,
              route_run_id: null,
              created_at: "2026-09-19T09:30:00Z",
              updated_at: "2026-09-19T09:30:00Z",
            },
          ],
          count: 1,
        },
      });
      return;
    }
    if (/\/response-cases\/[^/]+$/.test(path)) {
      await route.fulfill({
        json: {
          id: "33333333-3333-4333-8333-333333333333",
          pilot_slug: "jkuat",
          owner_user_id: "00000000-0000-4000-8000-000000000001",
          rule_id: "44444444-4444-4444-8444-444444444444",
          rule_name: "High Temperature Critical",
          mission_id: "55555555-5555-4555-8555-555555555555",
          mission_title: "Response Mission: High Temperature Critical",
          mission_status: "planned",
          status: "triage",
          severity: "critical",
          revision: 1,
          resolution_notes: null,
          dismissal_reason: null,
          acknowledged_at: null,
          started_at: null,
          completed_at: null,
          closed_at: null,
          dismissed_at: null,
          alert_count: 1,
          update_count: 0,
          route_run_id: null,
          created_at: "2026-09-19T09:30:00Z",
          updated_at: "2026-09-19T09:30:00Z",
          case: {
            id: "33333333-3333-4333-8333-333333333333",
            pilot_slug: "jkuat",
            owner_user_id: "00000000-0000-4000-8000-000000000001",
            status: "triage",
            severity: "critical",
            revision: 1,
            resolution_notes: null,
            dismissal_reason: null,
            acknowledged_at: null,
            started_at: null,
            completed_at: null,
            closed_at: null,
            dismissed_at: null,
            created_at: "2026-09-19T09:30:00Z",
            updated_at: "2026-09-19T09:30:00Z",
          },
          rule: {
            id: "44444444-4444-4444-8444-444444444444",
            pilot_slug: "jkuat",
            name: "High Temperature Critical",
            metric: "temperature_c",
            condition: "gt",
            threshold: 35.0,
            severity: "critical",
            response_mode: "case_and_mission",
            window_minutes: 60,
            is_active: true,
          },
          mission: {
            id: "55555555-5555-4555-8555-555555555555",
            pilot_slug: "jkuat",
            title: "Response Mission: High Temperature Critical",
            status: "planned",
            route_run_id: null,
            response_case_id: "33333333-3333-4333-8333-333333333333",
          },
          route: null,
          alerts: [
            {
              id: "66666666-6666-4666-8666-666666666666",
              kind: "forecast_threshold",
              title: "Forecast threshold triggered",
              message: "Forecast 36.2 °C exceeds threshold 35.0 °C",
              severity: "critical",
              payload: { metric: "temperature_c", value: 36.2, threshold: 35.0 },
              is_forecast: true,
              created_at: "2026-09-19T09:30:00Z",
            },
          ],
          updates: [],
          report: null,
          timeline: [],
          next_action: {
            stage: "Verify",
            action: "acknowledge",
            label: "Acknowledge alert and review evidence",
            description: "Confirm the signal was received and inspect whether it represents a forecast or observation.",
          },
        },
      });
      return;
    }
    if (path.endsWith("/admin/members")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/admin/audit-events")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/admin/data-sources")) {
      await route.fulfill({ json: { data: ["conduit", "forecast", "satellite", "terrain", "osm"].map((source) => ({ source, enabled: true, schedule: null, mapping: {}, latest_status: "success", latest_run_at: "2026-09-19T09:00:00Z", records_written: 10, error_code: null })), count: 5 } });
      return;
    }
    if (path.endsWith("/calibration/status")) {
      await route.fulfill({
        json: {
          status: "CALIBRATION_REQUIRED",
          sample_count: 0,
          active_model_version: null,
          required_fields: ["sample_id", "sampled_at", "geometry", "dry_matter_kg_ha", "method", "quadrat_area_m2"],
          message: "Field samples are required before biomass or carrying capacity can be calculated.",
        },
      });
      return;
    }
    if (path.endsWith("/telemetry")) {
      await route.fulfill({ json: { data: [{ metric: "temperature_c", value: 24.8, unit: "°C", observed_at: "2026-09-19T09:00:00Z", source: "conduit", quality_flags: [], model_version: null, station_id: "jkuat-conduit", depth_cm: null }], count: 1, from_time: "2026-09-18T00:00:00Z", to_time: "2026-09-19T00:00:00Z" } });
      return;
    }
    if (path.endsWith("/forecast")) {
      await route.fulfill({ json: { run_id: "22222222-2222-4222-8222-222222222222", source: "Open-Meteo", model_version: "open-meteo-best-match-v1", generated_at: "2026-09-19T09:00:00Z", fetched_at: "2026-09-19T09:01:00Z", valid_from: "2026-09-19T10:00:00Z", valid_to: "2026-09-22T09:00:00Z", count: 2, attribution: "Weather data by Open-Meteo.com", data: [{ valid_at: new Date(Date.now() + 3600000).toISOString(), temperature_c: 26, relative_humidity_pct: 58, precipitation_probability_pct: 20, precipitation_mm: 0, uv_index: 7, wind_speed_m_s: 3, wind_gust_m_s: 5, et0_mm: 0.2, quality_flags: ["FORECAST_NOT_OBSERVATION"] }] } });
      return;
    }
    if (path.endsWith("/scenes")) {
      await route.fulfill({ json: { data: [
        { id: "scene-new", source: "planetary-computer", collection: "sentinel-2-l2a", acquired_at: "2026-09-18T08:00:00Z", cloud_cover_pct: 8, processing_status: "complete", valid_fraction: 0.92, assets: {} },
        { id: "scene-old", source: "planetary-computer", collection: "sentinel-2-l2a", acquired_at: "2026-09-08T08:00:00Z", cloud_cover_pct: 12, processing_status: "complete", valid_fraction: 0.87, assets: {} },
      ], count: 2 } });
      return;
    }
    if (path.endsWith("/operations/ingestions")) {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/operations/status")) {
      await route.fulfill({ json: { generated_at: "2026-09-19T10:00:00Z", pilot_slug: url.searchParams.get("pilot") || "jkuat", worker: { status: "healthy", last_heartbeat_at: "2026-09-19T09:59:00Z" }, sources: ["conduit", "forecast", "satellite", "terrain", "osm"].map((source) => ({ pilot_slug: url.searchParams.get("pilot") || "jkuat", source, status: "healthy", latest_run_status: "success", latest_run_at: "2026-09-19T09:00:00Z", last_success_at: "2026-09-19T09:00:00Z", age_seconds: 3600, error_code: null, next_scheduled_at: "2026-09-19T12:00:00Z" })) } });
      return;
    }
    if (path.endsWith("/calibration/samples/coverage")) {
      await route.fulfill({ json: { type: "FeatureCollection", features: [], meta: { sample_count: 0, scene_matched_count: 0, unmatched_count: 0, match_window_days: 5, model_activation: "CALIBRATION_REQUIRED" } } });
      return;
    }
    if (path.endsWith("/cells/change")) {
      await route.fulfill({ json: { ...emptyCells, meta: { ...emptyCells.meta, layer: "delta_ndvi" } } });
      return;
    }
    if (path.endsWith("/cells")) {
      await route.fulfill({ json: emptyCells });
      return;
    }
    if (path.endsWith("/routes") && route.request().method() === "POST") {
      await route.fulfill({
        json: {
          id: "11111111-1111-4111-8111-111111111111",
          status: "complete",
          total_distance_m: 875,
          estimated_time_s: 690,
          geojson: { type: "FeatureCollection", features: [] },
          elevation_profile: [{ distance_m: 0, elevation_m: 1520 }, { distance_m: 875, elevation_m: 1532 }],
          diagnostics: { model_version: "routing-tobler-h3r9-v1" },
          quality_flags: ["water_missing_neutral"],
          not_applied_parameters: [],
          profile: "resource_aware",
        },
      });
      return;
    }
    if (path.endsWith("/routes") && route.request().method() === "GET") {
      await route.fulfill({ json: { data: [], count: 0 } });
      return;
    }
    if (path.endsWith("/gpx")) {
      await route.fulfill({
        contentType: "application/gpx+xml",
        headers: { "content-disposition": "attachment; filename=solarshepherd-route.gpx" },
        body: "<?xml version=\"1.0\"?><gpx version=\"1.1\"></gpx>",
      });
      return;
    }
    if (path.endsWith("/evidence")) {
      await route.fulfill({ json: { schema_version: "solarshepherd-route-evidence-v1" } });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "Test route not mocked." } } });
  });
  await page.route("https://tile.openstreetmap.org/**", (route) => route.abort());
  await page.route("https://tiles.example.test/**", (route) => route.fulfill({ json: { tilejson: "2.2.0", tiles: [], minzoom: 0, maxzoom: 14 } }));
}

test.beforeEach(async ({ page }) => {
  await mockOperationalApi(page);
});

test("navigates all five scientific screens and keeps capacity locked", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  await page.goto("/app/jkuat/telemetry");
  await expect(page.getByRole("heading", { level: 1, name: "Live telemetry" })).toBeVisible();

  for (const [path, heading] of [
    ["/app/jkuat/landscape", "Landscape explorer"],
    ["/app/jkuat/routes", "Route planner"],
    ["/app/jkuat/capacity", "Carrying capacity"],
    ["/app/jkuat/operations", "Operations"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }

  await page.goto("/app/jkuat/capacity");
  await expect(page.getByText("No biomass estimate is being displayed")).toBeVisible();
  await expect(page.getByText("CALIBRATION REQUIRED", { exact: true })).toBeVisible();
});

test("selects a route destination, calculates a route and exposes GPX export", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  await page.goto("/app/jkuat/routes");
  const map = page.getByLabel("Interactive geospatial map");
  // MapLibre and deck.gl live in a deliberately lazy-loaded chunk. Give that
  // scientific workspace time to initialise on slower CI and Windows hosts.
  await expect(map).toBeVisible({ timeout: 20_000 });
  await map.click({ position: { x: 360, y: 260 } });
  await page.getByRole("button", { name: "Calculate evidence route" }).click();

  await expect(page.getByText("Journey profile")).toBeVisible();
  await expect(page.getByText("0.88 km")).toBeVisible();
  await expect(page.getByRole("button", { name: "GPX" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Evidence", exact: true })).toBeEnabled();
});

test("keeps observations separate from the forecast outlook", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  await page.goto("/app/jkuat/telemetry");
  await expect(page.getByText("24.8")).toBeVisible();
  await page.getByRole("tab", { name: "72h outlook" }).click();
  await expect(page.getByText("forecast · not observed", { exact: true })).toBeVisible();
  await expect(page.getByText("Open-Meteo forecast", { exact: true }).first()).toBeVisible();
});

test("shows the public landing and starts a restricted guest session", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /Move livestock with evidence/i })).toBeVisible();
  await page.getByRole("button", { name: "Explore as guest" }).click();
  await expect(page).toHaveURL(/\/app\/jkuat\/dashboard$/);
  await expect(page.getByText("Guest session", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Missions" })).toHaveCount(0);
});

test("switches pilots, persists the choice and preserves deep links", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  await page.goto("/app/jkuat/landscape");
  await page.locator('select[aria-label="Active pilot"]:visible').selectOption("garissa");
  await expect(page).toHaveURL(/\/app\/garissa\/landscape$/);
  await expect(page.getByRole("heading", { level: 2, name: "Garissa" })).toBeVisible();
  await page.reload();
  await expect(page.locator('select[aria-label="Active pilot"]:visible')).toHaveValue("garissa");
  await page.goto("/app/not-a-pilot/telemetry");
  await expect(page).toHaveURL(/\/app\/jkuat\/telemetry$/);
  await expect(page.getByText(/Pilot “not-a-pilot” was not found/)).toBeVisible();
});

test("opens member field-work and management screens", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  for (const [path, heading] of [
    ["/app/jkuat/dashboard", /Good field work starts here/i],
    ["/app/jkuat/missions", "Missions"],
    ["/app/jkuat/responses", "Response Center"],
    ["/app/jkuat/samples", "Samples"],
    ["/app/jkuat/reports", "Mission reports"],
    ["/app/jkuat/alerts", "Alerts"],
    ["/app/jkuat/team", "Team"],
    ["/app/jkuat/data-sources", "Data sources"],
    ["/app/jkuat/settings", "Settings"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});

test("navigates response center and views episode detail", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("solarshepherd-dev-role", "member"));
  await page.goto("/app/jkuat/responses");
  await expect(page.getByRole("heading", { level: 1, name: "Response Center" })).toBeVisible();
  await expect(page.getByText("Response: High Temperature Critical").first()).toBeVisible();
  await expect(page.locator(".severity-chip.critical")).toBeVisible();
  await page.getByRole("link", { name: /Open Response Episode/i }).click();
  await expect(page).toHaveURL(/\/app\/jkuat\/responses\/33333333-3333-4333-8333-333333333333$/);
  await expect(page.getByRole("heading", { level: 1, name: "Response: High Temperature Critical" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Acknowledge Alert & Evidence/i })).toBeVisible();
});


