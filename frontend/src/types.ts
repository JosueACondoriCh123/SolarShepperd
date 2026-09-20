export interface Measurement {
  metric: string;
  value: number;
  unit: string;
  observed_at: string;
  source: string;
  quality_flags: string[];
  model_version: string | null;
  station_id: string | null;
  depth_cm: number | null;
}

export interface Pilot {
  slug: string;
  name: string;
  center: { latitude: number; longitude: number };
  radius_km: number;
  timezone: string;
  bbox: [number, number, number, number];
  boundary: GeoJSON.Polygon;
  observation_sources: string[];
  latest_observed_at: string | null;
  observation_status: "healthy" | "stale" | "unavailable" | "never_run";
}

export interface PilotsResponse {
  data: Pilot[];
  count: number;
  default_pilot_slug: string;
}

export interface StationProperties {
  station_id: string;
  name: string;
  source: string;
  role: "primary" | "regional_reference";
  distance_to_center_m: number;
  outside_pilot: boolean;
  latest_observed_at: string | null;
}

export interface PilotMapContext {
  pilot: Pilot;
  boundary: GeoJSON.Feature<GeoJSON.Polygon, { pilot_slug: string; radius_km: number }>;
  stations: GeoJSON.FeatureCollection<GeoJSON.Point, StationProperties>;
  water: GeoJSON.FeatureCollection<GeoJSON.Geometry, {
    name: string | null;
    feature_type: string;
    source: string;
    fetched_at: string;
    coverage_warning: string;
  }>;
  water_coverage_warning: string;
}

export interface SceneTiles {
  scene_id: string;
  pilot_slug: string;
  tilejson_url: string;
  source: string;
  acquired_at: string;
  attribution: string;
}

export interface TelemetryResponse {
  data: Measurement[];
  count: number;
  from_time: string;
  to_time: string;
}

export interface ForecastPoint {
  valid_at: string;
  temperature_c: number | null;
  relative_humidity_pct: number | null;
  precipitation_probability_pct: number | null;
  precipitation_mm: number | null;
  uv_index: number | null;
  wind_speed_m_s: number | null;
  wind_gust_m_s: number | null;
  et0_mm: number | null;
  quality_flags: string[];
}

export interface ForecastResponse {
  run_id: string | null;
  source: string;
  model_version: string | null;
  generated_at: string | null;
  fetched_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  data: ForecastPoint[];
  count: number;
  attribution: string;
}

export interface Scene {
  id: string;
  source: string;
  collection: string;
  acquired_at: string;
  cloud_cover_pct: number | null;
  processing_status: string;
  valid_fraction: number | null;
  assets: Record<string, unknown>;
}

export interface SceneResponse {
  data: Scene[];
  count: number;
}

export interface CellProperties {
  h3_index: string;
  value: number | null;
  unit: string;
  observed_at: string | null;
  source: string | null;
  quality_flags: string[];
  model_version: string | null;
  valid_fraction: number | null;
  scene_id: string | null;
  area_ha: number;
  water_distance_m: number | null;
  from_value?: number | null;
  to_value?: number | null;
  from_scene_id?: string;
  to_scene_id?: string;
}

export interface CellFeature {
  type: "Feature";
  id: string;
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: CellProperties;
}

export interface CellCollection {
  type: "FeatureCollection";
  features: CellFeature[];
  meta: { layer: string; count: number; biomass_calibrated: boolean };
}

export interface RouteResponse {
  id: string;
  status: "complete";
  total_distance_m: number;
  estimated_time_s: number;
  geojson: GeoJSON.FeatureCollection;
  elevation_profile: { distance_m: number; elevation_m: number }[];
  diagnostics: Record<string, unknown>;
  quality_flags: string[];
  not_applied_parameters: string[];
  profile: "fastest" | "resource_aware";
}

export interface CalibrationStatus {
  status: "CALIBRATION_REQUIRED" | "READY";
  sample_count: number;
  active_model_version: string | null;
  required_fields: string[];
  message: string;
}

export interface IngestionRun {
  id: string;
  source: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_seen: number;
  records_written: number;
  latency_ms: number | null;
  discovered_fields: string[];
  diagnostics: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
}

export interface IngestionResponse {
  data: IngestionRun[];
  count: number;
}

export interface OperationsStatus {
  generated_at: string;
  pilot_slug: string;
  sources: {
    source: string;
    pilot_slug: string;
    status: "healthy" | "stale" | "degraded" | "unavailable" | "never_run";
    latest_run_status: string | null;
    latest_run_at: string | null;
    last_success_at: string | null;
    age_seconds: number | null;
    error_code: string | null;
    next_scheduled_at: string | null;
  }[];
  worker: { status: "healthy" | "stale"; last_heartbeat_at: string | null };
}

export interface CalibrationCoverage {
  type: "FeatureCollection";
  features: GeoJSON.Feature<GeoJSON.Point, {
    sample_id: string;
    sampled_at: string;
    dry_matter_kg_ha: number;
    method: string;
    quadrat_area_m2: number;
    scene_id: string | null;
    scene_acquired_at: string | null;
  }>[];
  meta: {
    sample_count: number;
    scene_matched_count: number;
    unmatched_count: number;
    match_window_days: number;
    model_activation: "CALIBRATION_REQUIRED";
  };
}

export interface ApiErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

export interface DashboardData {
  generated_at: string;
  telemetry_latest_at: string | null;
  forecast_generated_at: string | null;
  forecast_valid_to: string | null;
  scene: { id: string; acquired_at: string; cloud_cover_pct: number | null } | null;
  active_mission: Mission | null;
  pending_samples: number;
  unread_alerts: number;
  calibration_status: "CALIBRATION_REQUIRED";
}

export interface Mission {
  id: string;
  title: string;
  description: string;
  status: "draft" | "planned" | "active" | "completed" | "cancelled";
  scheduled_start: string | null;
  scheduled_end: string | null;
  route_run_id: string | null;
  herd_tlu: number | null;
  notes: string;
  revision: number;
  started_at: string | null;
  completed_at: string | null;
  sample_count?: number;
  created_at: string;
  updated_at: string;
}

export interface SampleSubmission {
  id: string;
  sample_code: string;
  external_reference: string | null;
  mission_id: string | null;
  sampled_at: string;
  latitude: number;
  longitude: number;
  dry_matter_kg_ha: number;
  method: string;
  quadrat_area_m2: number;
  status: "draft" | "pending_review" | "approved" | "rejected";
  review_notes: string | null;
  attachment_count: number;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface TimelineEvent {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface MissionReport {
  id: string;
  mission_id: string;
  status: "queued" | "processing" | "ready" | "failed";
  parameters: Record<string, unknown>;
  evidence_manifest: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  downloads: { pdf: string | null; json: string | null };
}

export interface AlertRule {
  id: string;
  name: string;
  kind: "forecast_threshold" | "telemetry_stale" | "mission_reminder" | "sample_review";
  metric: string | null;
  comparator: string | null;
  threshold: number | null;
  lookahead_hours: number;
  cooldown_minutes: number;
  channels: ("in_app" | "email")[];
  enabled: boolean;
  last_triggered_at: string | null;
}

export interface UserAlert {
  id: string;
  kind: string;
  title: string;
  message: string;
  severity: string;
  payload: Record<string, unknown>;
  created_at: string;
  acknowledged_at: string | null;
}
