import { DatabaseZap, Play, Save } from "lucide-react";
import { useState } from "react";

import { apiGet, apiPatch, apiPost } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";

interface DataSourceRow {
  source: string;
  enabled: boolean;
  schedule: string | null;
  mapping: Record<string, unknown>;
  latest_status: string;
  latest_run_at: string | null;
  records_written: number;
  error_code: string | null;
}

export function DataSourcesPage() {
  const sources = useApi<{ data: DataSourceRow[]; count: number }>(
    () => apiGet("/admin/data-sources"),
    [],
  );
  const [schedules, setSchedules] = useState<Record<string, string>>({});
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const run = async (source: string) => {
    setError(""); setMessage("");
    try {
      await apiPost(`/admin/ingestions/${source}/run`, {});
      setMessage(`${source} ingestion queued.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ingestion could not be queued.");
    }
  };

  const save = async (source: DataSourceRow, schedule: string, mapping: string) => {
    setError("");
    try {
      const parsed = JSON.parse(mapping) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Mapping must be a JSON object.");
      }
      await apiPatch(`/admin/data-sources/${source.source}`, { schedule, mapping: parsed });
      setMessage(`${source.source} settings saved.`);
      await sources.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mapping must be valid JSON.");
    }
  };

  return <div className="page">
    <PageHeader kicker="12 / Manage" title="Data sources" description="Owner-only schedules, non-secret mappings and ingestion controls. Credentials never appear here." />
    {message && <p className="form-success notice-box">{message}</p>}
    {error && <p className="form-error notice-box">{error}</p>}
    {sources.loading && !sources.data ? <LoadingState label="Inspecting source health" /> : sources.error ? <EmptyState error title={sources.error.code} body={sources.error.message} /> : <section className="source-admin-grid">{sources.data?.data.map((source) => {
      const schedule = schedules[source.source] ?? source.schedule ?? "";
      const mapping = mappings[source.source] ?? JSON.stringify(source.mapping, null, 2);
      return <article className="panel source-admin-card" key={source.source}>
        <div className="panel-header"><div><span className="panel-kicker">{source.source.toUpperCase()}</span><h2>{source.source === "forecast" ? "Open-Meteo" : source.source}</h2></div><DatabaseZap /></div>
        <div className="source-health"><StatusBadge status={source.latest_status} /><span>{source.latest_run_at ? new Date(source.latest_run_at).toLocaleString() : "Never run"}</span><strong>{source.records_written} records</strong></div>
        {source.error_code && <p className="form-error">{source.error_code}</p>}
        <label><span>Schedule · human-readable</span><input placeholder="Every 3 hours" value={schedule} onChange={(event) => setSchedules({ ...schedules, [source.source]: event.target.value })} /></label>
        <label><span>Non-secret mapping · JSON</span><textarea value={mapping} onChange={(event) => setMappings({ ...mappings, [source.source]: event.target.value })} /></label>
        <div className="source-actions"><button className="button secondary" onClick={async () => { await apiPatch(`/admin/data-sources/${source.source}`, { enabled: !source.enabled, schedule }); await sources.reload(); }}>{source.enabled ? "Disable" : "Enable"}</button><button className="icon-button" aria-label={`Save ${source.source} settings`} onClick={() => void save(source, schedule, mapping)}><Save size={16} /></button><button className="button primary" disabled={!source.enabled} onClick={() => void run(source.source)}><Play size={15} /> Run now</button></div>
      </article>;
    })}</section>}
    <EvidenceNote>Only source names, schedules, health and normalized field mappings are exposed. API keys, email credentials and storage secrets remain server-side.</EvidenceNote>
  </div>;
}
