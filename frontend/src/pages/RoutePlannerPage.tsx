import { CheckCircle2, Clock3, Download, FileJson, Flag, MapPin, Navigation, Route as RouteIcon, Save, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, apiDownload, apiGet, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { LineChart } from "../components/LineChart";
import { PageHeader } from "../components/PageHeader";
import { ScienceMap } from "../components/ScienceMap";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { CellCollection, PilotMapContext, RouteResponse } from "../types";

type Coordinate = { latitude: number; longitude: number };

export function RoutePlannerPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const responseCaseId = searchParams.get("response");
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState("");
  const bbox = pilot.bbox.join(",");
  const [start, setStart] = useState<Coordinate>({
    latitude: pilot.center.latitude,
    longitude: pilot.center.longitude,
  });
  const [end, setEnd] = useState<Coordinate | null>(null);
  const [selectionMode, setSelectionMode] = useState<"start" | "end">("end");
  const [maxSlope, setMaxSlope] = useState(18);
  const [herdTlu, setHerdTlu] = useState("");
  const [profile, setProfile] = useState<"fastest" | "resource_aware">("resource_aware");
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [routeError, setRouteError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const surface = useApi<CellCollection>(
    () => apiGet(`/cells?bbox=${encodeURIComponent(bbox)}&layer=slope`),
    [bbox, pilot.slug],
  );
  const context = useApi<PilotMapContext>(
    () => apiGet(`/pilots/${pilot.slug}/context`),
    [pilot.slug],
    120_000,
  );

  useEffect(() => {
    setStart({ latitude: pilot.center.latitude, longitude: pilot.center.longitude });
    setEnd(null);
    setRoute(null);
    setRouteError(null);
    setSelectionMode("end");
  }, [pilot.center.latitude, pilot.center.longitude, pilot.slug]);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const endpointCoordinates = useMemo(
    () => ({
      start: [start.longitude, start.latitude] as [number, number],
      end: end ? ([end.longitude, end.latitude] as [number, number]) : null,
    }),
    [start, end],
  );

  const handleMapClick = (longitude: number, latitude: number) => {
    if (selectionMode === "start") {
      setStart({ longitude, latitude });
      setSelectionMode("end");
    } else {
      setEnd({ longitude, latitude });
    }
    setRoute(null);
  };

  const calculate = async () => {
    if (!end) return;
    setSubmitting(true);
    setRouteError(null);
    try {
      const result = await apiPost<RouteResponse>("/routes", {
        start,
        end,
        max_slope_deg: maxSlope,
        herd_tlu: herdTlu ? Number(herdTlu) : null,
        profile,
      });
      setRoute(result);
    } catch (reason) {
      setRouteError(reason instanceof ApiError ? reason : new ApiError("ROUTE_ERROR", String(reason)));
      setRoute(null);
    } finally {
      setSubmitting(false);
    }
  };

  const hours = route ? route.estimated_time_s / 3_600 : 0;
  const inputs = route?.diagnostics.inputs_as_of as Record<string, unknown> | undefined;

  const openMission = () => {
    if (route) window.location.assign(`/app/${pilot.slug}/missions?route=${route.id}`);
  };

  const attachToResponse = async () => {
    if (!route || !responseCaseId) return;
    setAttaching(true);
    setAttachError("");
    try {
      const caseDetail = await apiGet<{ revision: number }>(`/response-cases/${responseCaseId}`);
      await apiPost(`/response-cases/${responseCaseId}/route`, {
        route_id: route.id,
        revision: caseDetail.revision,
      });
      navigate(`/app/${pilot.slug}/responses/${responseCaseId}`);
    } catch (err) {
      setAttachError(err instanceof Error ? err.message : "Failed to attach route to response episode.");
    } finally {
      setAttaching(false);
    }
  };

  return (
    <div className="page map-page">
      <PageHeader
        kicker="03 / Movement intelligence"
        title="Route planner"
        description="A* travel-time routes across real terrain with bounded UV, forage and water adjustments."
        actions={
          route &&
          !auth.isGuest && (
            <div className="page-actions">
              {responseCaseId ? (
                <button
                  className="button primary"
                  disabled={attaching}
                  onClick={() => void attachToResponse()}
                >
                  <CheckCircle2 size={16} /> {attaching ? "Attaching..." : "Attach to Response Episode"}
                </button>
              ) : (
                <button className="button secondary" onClick={openMission}>
                  <Save size={16} /> Use in mission
                </button>
              )}
              <button
                className="button secondary"
                onClick={() =>
                  void apiDownload(
                    `/routes/${route.id}/evidence`,
                    `solarshepherd-${route.id}-evidence.json`,
                  )
                }
              >
                <FileJson size={16} /> Evidence
              </button>
              <button
                className="button secondary"
                onClick={() =>
                  void apiDownload(`/routes/${route.id}/gpx`, `solarshepherd-${route.id}.gpx`)
                }
              >
                <Download size={16} /> GPX
              </button>
            </div>
          )
        }
      />

      {responseCaseId && (
        <div className="panel response-context-banner">
          <ShieldAlert size={18} />
          <div>
            <strong>Response Episode {responseCaseId.slice(0, 8)}... Active</strong>
            <p>
              Plan and verify a terrain-safe route, then click "Attach to Response Episode" to lock this route for operational field response.
            </p>
          </div>
        </div>
      )}

      {attachError && <p className="form-error notice-box">{attachError}</p>}

      <div className="route-layout">
        <aside className="route-config panel">
          <div className="panel-header compact">
            <div><span className="panel-kicker">EXPEDITION</span><h2>Route constraints</h2></div>
            <SlidersHorizontal size={18} />
          </div>

          <div className="endpoint-switch">
            <button className={selectionMode === "start" ? "active" : ""} onClick={() => setSelectionMode("start")}><MapPin size={16} /> Set start</button>
            <button className={selectionMode === "end" ? "active" : ""} onClick={() => setSelectionMode("end")}><Flag size={16} /> Set destination</button>
          </div>

          <div className="coordinate-block start">
            <span className="coordinate-marker">A</span>
            <div><label>Start</label><strong>{start.latitude.toFixed(5)}, {start.longitude.toFixed(5)}</strong></div>
          </div>
          <div className="coordinate-line" />
          <div className="coordinate-block end">
            <span className="coordinate-marker">B</span>
            <div><label>Destination</label><strong>{end ? `${end.latitude.toFixed(5)}, ${end.longitude.toFixed(5)}` : "Select on map"}</strong></div>
          </div>

          <label className="field-label">
            <span><strong>Maximum slope</strong><small>{maxSlope}°</small></span>
            <input type="range" min={5} max={35} value={maxSlope} onChange={(event) => setMaxSlope(Number(event.target.value))} />
          </label>
          <label className="field-label">
            <span><strong>Routing profile</strong><small>Versioned weights</small></span>
            <select className="field-select" value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}>
              <option value="fastest">Fastest · terrain only</option>
              <option value="resource_aware">Resource-aware</option>
            </select>
          </label>
          <label className="field-label">
            <span><strong>Herd size</strong><small>TLU · recorded, not applied</small></span>
            <input type="number" min="1" placeholder="Optional" value={herdTlu} onChange={(event) => setHerdTlu(event.target.value)} />
          </label>
          <div className="model-note">
            Herd size will affect GCH only after biomass calibration. It does not change walking speed in this model.
          </div>
          <button className="button primary wide" disabled={!end || submitting || !online} onClick={() => void calculate()}>
            {submitting ? <><span className="button-spinner" /> Calculating</> : <><Navigation size={17} /> Calculate evidence route</>}
          </button>
          {!online && <div className="model-note danger">Offline snapshots remain available, but new routes require the API.</div>}
        </aside>

        <section className="route-map panel">
          <ScienceMap
            pilot={pilot}
            context={context.data}
            cells={surface.data}
            layer="slope"
            route={route?.geojson || null}
            start={endpointCoordinates.start}
            end={endpointCoordinates.end}
            onCoordinateClick={handleMapClick}
          />
          <div className="map-stage-label"><span className="signal-dot amber" /> {selectionMode === "start" ? "Click map to set start" : "Click map to set destination"}</div>
          {surface.loading && <div className="map-overlay-state"><LoadingState label="Reading terrain surface" /></div>}
          {routeError && <div className="route-error-card"><EmptyState error title={routeError.code} body={routeError.message} /></div>}
        </section>

        <aside className="route-results panel">
          {route ? (
            <>
              <div className="panel-header compact">
                <div><span className="panel-kicker">ROUTE READY</span><h2>Journey profile</h2></div>
                <StatusBadge status="complete" />
              </div>
              <div className="route-kpis">
                <div><RouteIcon size={18} /><span>Distance</span><strong>{(route.total_distance_m / 1_000).toFixed(2)} km</strong></div>
                <div><Clock3 size={18} /><span>Travel time</span><strong>{hours < 1 ? `${Math.round(hours * 60)} min` : `${hours.toFixed(1)} h`}</strong></div>
              </div>
              <div className="route-profile-label"><span>Profile</span><strong>{route.profile.replaceAll("_", " ")}</strong></div>
              <div className="segment-legend"><span>Lower cost</span><i /><span>Higher cost</span></div>
              <div className="profile-chart">
                <span className="panel-kicker">ELEVATION PROFILE</span>
                <LineChart
                  height={190}
                  unit="m"
                  series={[{
                    label: "Elevation",
                    color: "#176b45",
                    values: route.elevation_profile.map((point) => ({ x: point.distance_m, y: point.elevation_m })),
                  }]}
                />
              </div>
              <div className="quality-list">
                <strong>Data quality</strong>
                {route.quality_flags.length ? route.quality_flags.map((flag) => <span key={flag}>{flag.replaceAll("_", " ")}</span>) : <span>All route factors available</span>}
              </div>
              {inputs && (
                <div className="provenance-list">
                  <strong>Inputs as of</strong>
                  <span>UV · {inputs.uv_observed_at ? new Date(String(inputs.uv_observed_at)).toLocaleString() : "neutral / unavailable"}</span>
                  <span>Sentinel · {inputs.satellite_acquired_at ? new Date(String(inputs.satellite_acquired_at)).toLocaleDateString() : "unavailable"}</span>
                  <span>OSM water · {inputs.water ? "documented snapshot" : "neutral / unavailable"}</span>
                </div>
              )}
            </>
          ) : (
            <EmptyState title="No route calculated" body="Choose a destination on the map. Routing stays unavailable until real Copernicus terrain has been ingested." />
          )}
        </aside>
      </div>
      <EvidenceNote>Colored segments expose the bounded cost multiplier. Forecast conditions remain advisory and do not alter this route.</EvidenceNote>
    </div>
  );
}
