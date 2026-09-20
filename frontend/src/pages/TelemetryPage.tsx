import {
  CloudRain,
  Droplets,
  Gauge,
  RefreshCw,
  Sun,
  ThermometerSun,
  Waves,
  Wind,
} from "lucide-react";
import { useMemo, useState } from "react";

import { apiGet } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { LineChart } from "../components/LineChart";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import type { ForecastPoint, ForecastResponse, Measurement, TelemetryResponse } from "../types";

const metricCatalog = [
  { key: "temperature_c", forecastKey: "temperature_c", label: "Air temperature", unit: "°C", icon: ThermometerSun, color: "#d95d39", accent: "amber" as const },
  { key: "relative_humidity_pct", forecastKey: "relative_humidity_pct", label: "Relative humidity", unit: "%", icon: Droplets, color: "#3478b8", accent: "blue" as const },
  { key: "uv_index", forecastKey: "uv_index", label: "UV index", unit: "index", icon: Sun, color: "#c07b00", accent: "amber" as const },
  { key: "wind_speed_m_s", forecastKey: "wind_speed_m_s", label: "Wind speed", unit: "m/s", icon: Wind, color: "#5e4fa2", accent: "violet" as const },
  { key: "precipitation_mm", forecastKey: "precipitation_mm", label: "Precipitation", unit: "mm", icon: CloudRain, color: "#2469a0", accent: "blue" as const },
  { key: "et0_mm_day", forecastKey: "et0_mm", label: "Reference ET₀", unit: "mm", icon: Gauge, color: "#23845c", accent: "green" as const },
  { key: "soil_moisture_surface_pct", label: "Surface moisture", unit: "%", icon: Droplets, color: "#168f6d", accent: "blue" as const },
  { key: "soil_moisture_deep_pct", label: "Deep moisture", unit: "%", icon: Waves, color: "#6746a5", accent: "violet" as const },
];

function latestFor(measurements: Measurement[], metric: string) {
  const values = measurements.filter((item) => item.metric === metric);
  return { latest: values.at(-1), previous: values.at(-2) };
}

function forecastValue(point: ForecastPoint, key: string): number | null {
  return point[key as keyof ForecastPoint] as number | null;
}

export function TelemetryPage() {
  const [rangeHours, setRangeHours] = useState(24);
  const [mode, setMode] = useState<"observed" | "forecast">("observed");
  const [chartMetric, setChartMetric] = useState("temperature_c");
  const from = useMemo(() => new Date(Date.now() - rangeHours * 3_600_000).toISOString(), [rangeHours]);
  const observed = useApi<TelemetryResponse>(
    () => apiGet(`/telemetry?from=${encodeURIComponent(from)}`),
    [from],
    60_000,
  );
  const forecast = useApi<ForecastResponse>(() => apiGet("/forecast?hours=72"), [], 180_000);
  const measurements = observed.data?.data || [];
  const forecastPoints = forecast.data?.data || [];
  const observedMetrics = new Set(measurements.map((item) => item.metric));
  const availableObserved = metricCatalog.filter((item) => observedMetrics.has(item.key));
  const availableForecast = metricCatalog.filter(
    (item) => item.forecastKey && forecastPoints.some((point) => forecastValue(point, item.forecastKey) != null),
  );
  const definitions = mode === "observed" ? availableObserved : availableForecast;
  const effectiveMetric = definitions.some((item) => item.key === chartMetric)
    ? chartMetric
    : definitions[0]?.key;
  const definition = definitions.find((item) => item.key === effectiveMetric);
  const latestTimestamp = measurements.at(-1)?.observed_at;
  const isFresh = latestTimestamp
    ? Date.now() - new Date(latestTimestamp).getTime() < 2 * 3_600_000
    : false;
  const next24 = forecastPoints.filter((point) => {
    const validAt = new Date(point.valid_at).getTime();
    return validAt >= Date.now() - 3_600_000 && validAt <= Date.now() + 24 * 3_600_000;
  });
  const loading = mode === "observed" ? observed.loading : forecast.loading;
  const error = mode === "observed" ? observed.error : forecast.error;
  const reload = mode === "observed" ? observed.reload : forecast.reload;

  const chartValues = definition
    ? mode === "observed"
      ? measurements
          .filter((item) => item.metric === definition.key)
          .map((item) => ({ x: new Date(item.observed_at).getTime(), y: item.value }))
      : forecastPoints
          .filter((item) => forecastValue(item, definition.forecastKey!) != null)
          .map((item) => ({
            x: new Date(item.valid_at).getTime(),
            y: forecastValue(item, definition.forecastKey!)!,
          }))
    : [];

  return (
    <div className="page">
      <PageHeader
        kicker="01 / Ground truth"
        title="Live telemetry"
        description="Direct station observations and a clearly separated 72-hour weather outlook."
        actions={
          <div className="header-controls">
            {mode === "observed" && (
              <label className="select-control">
                <span>Window</span>
                <select value={rangeHours} onChange={(event) => setRangeHours(Number(event.target.value))}>
                  <option value={24}>Last 24 hours</option>
                  <option value={168}>Last 7 days</option>
                  <option value={720}>Last 30 days</option>
                </select>
              </label>
            )}
            <button className="icon-button" onClick={() => void reload()} aria-label={`Refresh ${mode}`}>
              <RefreshCw size={18} />
            </button>
          </div>
        }
      />

      <div className="mode-tabs" role="tablist" aria-label="Telemetry data type">
        <button role="tab" aria-selected={mode === "observed"} className={mode === "observed" ? "active" : ""} onClick={() => setMode("observed")}>Observed</button>
        <button role="tab" aria-selected={mode === "forecast"} className={mode === "forecast" ? "active" : ""} onClick={() => setMode("forecast")}>72h outlook</button>
      </div>

      <div className="context-strip">
        {mode === "observed" ? (
          <>
            <div><span className={isFresh ? "signal-dot" : "signal-dot muted"} /><strong>Conduit@Empathy</strong></div>
            <span>{latestTimestamp ? `Latest observation ${new Date(latestTimestamp).toLocaleString()}` : "No normalized observation received"}</span>
            <StatusBadge status={measurements.length ? (isFresh ? "live" : "delayed") : "awaiting data"} />
          </>
        ) : (
          <>
            <div><span className="signal-dot amber" /><strong>Open-Meteo forecast</strong></div>
            <span>{forecast.data?.generated_at ? `Generated ${new Date(forecast.data.generated_at).toLocaleString()}` : "No forecast ingested"}</span>
            <StatusBadge status="forecast · not observed" />
          </>
        )}
      </div>

      {loading && !(mode === "observed" ? observed.data : forecast.data) ? (
        <LoadingState />
      ) : error ? (
        <EmptyState error title={error.code} body={error.message} action={<button onClick={() => void reload()}>Try again</button>} />
      ) : definitions.length === 0 ? (
        <EmptyState
          title={mode === "observed" ? "No mapped observations are available" : "No forecast has been ingested"}
          body={mode === "observed" ? "Run Conduit ingestion and configure only verified field mappings. No values are guessed." : "Run the protected forecast ingestion. Forecast values never backfill station observations."}
        />
      ) : (
        <>
          <section className="metric-grid">
            {mode === "observed" ? availableObserved.map((item) => {
              const { latest, previous } = latestFor(measurements, item.key);
              return (
                <MetricCard
                  key={item.key}
                  label={item.label}
                  value={latest?.value ?? null}
                  previous={previous?.value ?? null}
                  unit={latest?.unit || item.unit}
                  observedAt={latest?.observed_at}
                  source={latest?.source}
                  qualityFlags={latest?.quality_flags}
                  modelVersion={latest?.model_version}
                  icon={item.icon}
                  accent={item.accent}
                />
              );
            }) : availableForecast.map((item) => {
              const values = next24
                .map((point) => forecastValue(point, item.forecastKey!))
                .filter((value): value is number => value != null);
              const additive = item.forecastKey === "precipitation_mm" || item.forecastKey === "et0_mm";
              const value = values.length
                ? (additive ? values.reduce((total, current) => total + current, 0) : Math.max(...values))
                : null;
              return (
                <MetricCard
                  key={item.key}
                  label={`${additive ? "24h total" : "24h maximum"} · ${item.label}`}
                  value={value}
                  unit={item.unit}
                  observedAt={next24.at(-1)?.valid_at}
                  source="Open-Meteo forecast"
                  qualityFlags={["FORECAST_NOT_OBSERVATION"]}
                  modelVersion={forecast.data?.model_version}
                  icon={item.icon}
                  accent={item.accent}
                />
              );
            })}
          </section>

          <section className="panel chart-panel">
            <div className="panel-header">
              <div><span className="panel-kicker">{mode === "observed" ? "MEASURED SERIES" : "MODEL OUTLOOK"}</span><h2>{definition?.label}</h2></div>
              <label className="select-control">
                <span>Series</span>
                <select value={effectiveMetric} onChange={(event) => setChartMetric(event.target.value)}>
                  {definitions.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}
                </select>
              </label>
            </div>
            <LineChart series={[{ label: definition?.label || "Series", color: definition?.color || "#23845c", values: chartValues }]} unit={definition?.unit} height={285} />
          </section>
        </>
      )}

      <EvidenceNote>
        {mode === "observed"
          ? "These cards report only fields mapped from the station or transparent derived models. Missing sensors remain visibly absent."
          : "This outlook is model guidance for planning. It is stored separately and never replaces a Conduit observation."}
      </EvidenceNote>
    </div>
  );
}
