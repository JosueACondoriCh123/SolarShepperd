import { ChevronDown, ChevronUp, Download, FileJson2, FileText, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiDownload, apiGet, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import type { Mission, MissionReport } from "../types";

interface EvidenceManifest {
  schema_version?: string;
  route?: {
    distance_m?: number | null;
    estimated_time_s?: number | null;
  };
  sources?: {
    telemetry_latest_at?: string | null;
    forecast_generated_at?: string | null;
    sentinel_scene_id?: string | null;
    sentinel_acquired_at?: string | null;
  };
  approved_samples?: {
    sample_code: string;
    sampled_at: string;
  }[];
}

export function ReportsPage() {
  const auth = useAuth();
  const [searchParams] = useSearchParams();
  const initialMissionId = searchParams.get("mission") || "";

  const reports = useApi<{ data: MissionReport[]; count: number }>(
    () => apiGet("/reports"),
    [],
    10_000,
  );
  const missions = useApi<{ data: Mission[]; count: number }>(() => apiGet("/missions"), []);
  const [missionId, setMissionId] = useState(initialMissionId);
  const [expandedReportId, setExpandedReportId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialMissionId) setMissionId(initialMissionId);
  }, [initialMissionId]);

  if (auth.isGuest) {
    return (
      <div className="page">
        <PageHeader kicker="07 / Evidence" title="Reports" description="Versioned mission evidence is available to members." />
        <EmptyState title="Reports require an account" body="Guest sessions cannot generate or export private mission evidence." action={<Link className="button primary" to="/signup">Create account</Link>} />
      </div>
    );
  }

  const create = async () => {
    if (!missionId) return;
    setError("");
    try {
      await apiPost("/reports", { mission_id: missionId });
      setMissionId("");
      await reports.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The report could not be queued.");
    }
  };

  const download = async (report: MissionReport, format: "pdf" | "json") => {
    setError("");
    try {
      await apiDownload(
        `/reports/${report.id}/download/${format}`,
        `solarshepherd-${report.id}.${format}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The download failed.");
    }
  };

  return (
    <div className="page">
      <PageHeader kicker="07 / Evidence" title="Mission reports" description="Generate an immutable PDF summary and machine-readable JSON receipt from mission evidence." />
      <section className="panel report-builder">
        <div>
          <span className="panel-kicker">NEW SNAPSHOT</span>
          <h2>Generate evidence package</h2>
          <p>The worker captures the current route, weather, landscape, approved samples, sources and quality flags.</p>
        </div>
        <label>
          <span>Mission</span>
          <select value={missionId} onChange={(event) => setMissionId(event.target.value)}>
            <option value="">Choose a mission</option>
            {missions.data?.data.map((mission) => (
              <option key={mission.id} value={mission.id}>
                {mission.title} · {mission.status}
              </option>
            ))}
          </select>
        </label>
        <button className="button primary" disabled={!missionId} onClick={() => void create()}>
          <Plus size={15} /> Generate
        </button>
      </section>
      {error && <p className="form-error notice-box">{error}</p>}
      {reports.loading && !reports.data ? (
        <LoadingState label="Loading evidence packages" />
      ) : reports.error ? (
        <EmptyState error title={reports.error.code} body={reports.error.message} />
      ) : reports.data?.data.length ? (
        <section className="report-list">
          {reports.data.data.map((report) => {
            const mission = missions.data?.data.find((item) => item.id === report.mission_id);
            const isExpanded = expandedReportId === report.id;
            const manifest = (report.evidence_manifest || {}) as EvidenceManifest;
            const samplesList = manifest.approved_samples || [];
            const routeData = manifest.route || {};
            const sourcesData = manifest.sources || {};

            return (
              <article className="panel report-card" key={report.id}>
                <div className="report-icon">
                  <FileText />
                </div>
                <div>
                  <StatusBadge status={report.status} />
                  <h2>{String(report.parameters.title || mission?.title || "Mission evidence")}</h2>
                  <p>Requested {new Date(report.created_at).toLocaleString()}</p>
                  {report.error_message && <p className="form-error">{report.error_message}</p>}
                  {report.status === "ready" && (
                    <button
                      type="button"
                      className="report-evidence-toggle"
                      onClick={() => setExpandedReportId(isExpanded ? null : report.id)}
                    >
                      {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      {isExpanded ? "Hide evidence breakdown" : "View evidence breakdown"}
                    </button>
                  )}
                </div>
                <div className="report-downloads">
                  <button disabled={report.status !== "ready"} onClick={() => void download(report, "pdf")}>
                    <Download size={15} /> PDF
                  </button>
                  <button disabled={report.status !== "ready"} onClick={() => void download(report, "json")}>
                    <FileJson2 size={15} /> JSON
                  </button>
                </div>
                {isExpanded && (
                  <div className="report-evidence-details">
                    <span className="panel-kicker">EVIDENCE MANIFEST SUMMARY</span>
                    <div className="report-evidence-grid">
                      <div className="report-evidence-stat">
                        <span>Approved samples</span>
                        <strong>{samplesList.length} observation{samplesList.length === 1 ? "" : "s"}</strong>
                        {samplesList.length > 0 && (
                          <small style={{ color: "var(--muted)" }}>
                            {samplesList.slice(0, 3).map((s) => s.sample_code).join(", ")}
                            {samplesList.length > 3 ? ` +${samplesList.length - 3} more` : ""}
                          </small>
                        )}
                      </div>
                      <div className="report-evidence-stat">
                        <span>Evidence route</span>
                        <strong>
                          {routeData.distance_m ? `${(routeData.distance_m / 1000).toFixed(2)} km` : "No route"}
                        </strong>
                        {routeData.estimated_time_s && (
                          <small style={{ color: "var(--muted)" }}>
                            ~{Math.round(routeData.estimated_time_s / 60)} min estimated
                          </small>
                        )}
                      </div>
                      <div className="report-evidence-stat">
                        <span>Satellite scene</span>
                        <strong>{sourcesData.sentinel_scene_id || "None recorded"}</strong>
                        {sourcesData.sentinel_acquired_at && (
                          <small style={{ color: "var(--muted)" }}>
                            Acquired {new Date(sourcesData.sentinel_acquired_at).toLocaleDateString()}
                          </small>
                        )}
                      </div>
                      <div className="report-evidence-stat">
                        <span>Telemetry & climate</span>
                        <strong>{sourcesData.telemetry_latest_at ? "Telemetry linked" : "No station sync"}</strong>
                        {sourcesData.forecast_generated_at && (
                          <small style={{ color: "var(--muted)" }}>
                            Forecast run: {new Date(sourcesData.forecast_generated_at).toLocaleDateString()}
                          </small>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      ) : (
        <EmptyState title="No evidence packages" body="Choose a mission to create its first versioned report." />
      )}
      <EvidenceNote>Reports preserve the evidence available at generation time. Biomass and GCH remain explicitly marked CALIBRATION_REQUIRED.</EvidenceNote>
    </div>
  );
}
