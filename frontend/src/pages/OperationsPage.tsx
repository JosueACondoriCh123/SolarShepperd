import { Activity, Clock, Database, RefreshCw, Satellite, ServerCog } from "lucide-react";
import { useState } from "react";

import { apiGet } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { SourceReadinessMatrix } from "../components/SourceReadinessMatrix";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { IngestionResponse, OperationsStatus, SceneResponse } from "../types";

export function OperationsPage() {
  const { pilot } = usePilot();
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState("all");
  const runs = useApi<IngestionResponse>(() => apiGet("/operations/ingestions?limit=50"), [], 30_000);
  const scenes = useApi<SceneResponse>(() => apiGet("/scenes?limit=12"), [], 60_000);
  const status = useApi<OperationsStatus>(() => apiGet("/operations/status"), [], 30_000);
  const successful = runs.data?.data.filter((run) => run.status === "success").length || 0;
  const failed = runs.data?.data.filter((run) => run.status === "failed").length || 0;
  const latestRun = runs.data?.data[0];
  const sourceRows = status.data?.sources.filter((source) => sourceFilter === "all" || source.source === sourceFilter) || [];

  const reload = () => {
    void runs.reload();
    void scenes.reload();
    void status.reload();
  };

  return (
    <div className="page">
      <PageHeader
        kicker={`05 / ${pilot.name} provenance`}
        title="Operations"
        description="A safe, read-only view of source synchronization, processing and data quality."
        actions={<button className="button secondary" onClick={reload}><RefreshCw size={16} /> Refresh</button>}
      />

      <section className="ops-summary">
        <article><div className="ops-icon"><Activity size={19} /></div><span>Recent successful runs</span><strong>{successful}</strong><small>of {runs.data?.count || 0} shown</small></article>
        <article><div className="ops-icon amber"><Clock size={19} /></div><span>Latest synchronization</span><strong>{latestRun ? new Date(latestRun.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong><small>{latestRun?.source || "No jobs yet"}</small></article>
        <article><div className="ops-icon blue"><Satellite size={19} /></div><span>Sentinel scenes</span><strong>{scenes.data?.count || 0}</strong><small>catalogued acquisitions</small></article>
        <article><div className="ops-icon danger"><ServerCog size={19} /></div><span>Failed runs</span><strong>{failed}</strong><small>inspect before retrying</small></article>
      </section>

      <section className="panel readiness-matrix">
        <div className="panel-header"><div><span className="panel-kicker">SOURCE READINESS</span><h2>{pilot.name} freshness and schedules</h2></div><div className="operations-filters"><label className="select-control"><span>Source</span><select aria-label="Filter source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">All sources</option>{status.data?.sources.map((source) => <option key={source.source} value={source.source}>{source.source.replaceAll("_", " ")}</option>)}</select></label><StatusBadge status={`worker ${status.data?.worker.status || "unknown"}`} /></div></div>
        {status.loading && !status.data ? <LoadingState /> : status.error ? <EmptyState error title={status.error.code} body={status.error.message} /> : (
          <SourceReadinessMatrix sources={sourceRows} />
        )}
      </section>

      <div className="operations-grid">
        <section className="panel runs-panel">
          <div className="panel-header">
            <div><span className="panel-kicker">INGESTION LEDGER</span><h2>Source runs</h2></div>
            <span className="data-note">Auto-refresh · 30 sec</span>
          </div>
          {runs.loading && !runs.data ? <LoadingState /> : runs.error ? (
            <EmptyState error title={runs.error.code} body={runs.error.message} />
          ) : !runs.data?.data.length ? (
            <EmptyState title="No ingestion runs recorded" body="Use the protected admin endpoint to start Conduit, satellite, terrain or OSM ingestion." />
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>Source</th><th>Status</th><th>Started</th><th>Written</th><th>Latency</th></tr></thead>
                <tbody>
                  {runs.data.data.map((run) => (
                    <tr key={run.id} onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)} className={expandedRun === run.id ? "expanded" : ""}>
                      <td><Database size={14} /> <strong>{run.source}</strong></td>
                      <td><StatusBadge status={run.status} /></td>
                      <td>{new Date(run.started_at).toLocaleString()}</td>
                      <td>{run.records_written.toLocaleString()}</td>
                      <td>{run.latency_ms == null ? "—" : `${run.latency_ms} ms`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {expandedRun && (() => {
            const run = runs.data?.data.find((item) => item.id === expandedRun);
            if (!run) return null;
            return (
              <div className="run-detail">
                <div><span>Run ID</span><code>{run.id}</code></div>
                {run.error_code && <div><span>Error</span><strong>{run.error_code}</strong><p>{run.error_message}</p></div>}
                {run.discovered_fields.length > 0 && <div><span>Discovered fields</span><div className="field-chips">{run.discovered_fields.map((field) => <code key={field}>{field}</code>)}</div></div>}
                <div><span>Diagnostics</span><pre>{JSON.stringify(run.diagnostics, null, 2)}</pre></div>
              </div>
            );
          })()}
        </section>

        <section className="panel scenes-panel">
          <div className="panel-header">
            <div><span className="panel-kicker">STAC CATALOG</span><h2>Satellite acquisitions</h2></div>
            <Satellite size={20} />
          </div>
          {scenes.loading && !scenes.data ? <LoadingState /> : !scenes.data?.data.length ? (
            <EmptyState title="No Sentinel-2 scenes" body="Run satellite ingestion after the H3 grid is initialized." />
          ) : (
            <div className="scene-list">
              {scenes.data.data.map((scene) => (
                <article key={scene.id}>
                  <div><strong>{new Date(scene.acquired_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</strong><small>{scene.id}</small></div>
                  <div className="scene-measures"><span>{scene.cloud_cover_pct?.toFixed(1) ?? "—"}% cloud</span><span>{scene.valid_fraction == null ? "—" : `${(scene.valid_fraction * 100).toFixed(0)}% valid`}</span></div>
                  <StatusBadge status={scene.processing_status} />
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="security-note"><ServerCog size={18} /><span>Administrative retries require the server-side <code>X-Admin-Token</code>. This public console cannot access or reveal it.</span></div>
      <EvidenceNote>Freshness is evaluated per source because station, forecast, satellite, terrain and OSM data update on different schedules.</EvidenceNote>
    </div>
  );
}
