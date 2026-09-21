import {
  ArrowRight,
  Filter,
  RotateCw,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { apiGet } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { ResponseCaseSummary } from "../types";

const STAGES = ["Detect", "Verify", "Route", "Respond", "Prove"] as const;

function getStageIndex(status: ResponseCaseSummary["status"], ackAt: string | null): number {
  switch (status) {
    case "triage":
      return ackAt ? 2 : 1; // 1 = Verify, 2 = Route
    case "ready":
      return 2; // Route ready, next is Respond
    case "responding":
      return 3; // Respond in progress
    case "review":
      return 4; // Prove in review
    case "closed":
      return 5; // Prove completed
    case "dismissed":
      return 1;
    default:
      return 0;
  }
}

export function ResponsesPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [severityFilter, setSeverityFilter] = useState<string>("all");

  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "all") params.set("status", statusFilter);
    if (severityFilter !== "all") params.set("severity", severityFilter);
    return params.toString();
  }, [statusFilter, severityFilter]);

  const endpoint = `/response-cases${queryParams ? `?${queryParams}` : ""}`;
  const casesApi = useApi<{ data: ResponseCaseSummary[]; count: number }>(
    () => apiGet(endpoint),
    [endpoint, pilot.slug],
    15_000,
  );

  if (auth.isGuest) {
    return (
      <div className="page">
        <PageHeader
          kicker="09 / Response Center"
          title="Response Center"
          description="Structured Alert-to-Action workflow: Detect → Verify → Route → Respond → Prove."
        />
        <EmptyState
          title="Operator account required"
          body="Response Center operations require authenticated field privileges."
          action={<Link className="button primary" to="/signup">Create account</Link>}
        />
      </div>
    );
  }

  const cases = casesApi.data?.data || [];

  return (
    <div className="page">
      <PageHeader
        kicker="09 / Response Center"
        title="Response Center"
        description="Operational incident workflow: Detect → Verify → Route → Respond → Prove. Signals open planned missions without automated movement."
        actions={
          <div className="header-controls">
            <button
              className="button secondary"
              onClick={() => void casesApi.reload()}
              title="Refresh episodes"
            >
              <RotateCw size={15} /> Refresh
            </button>
            <Link to={`/app/${pilot.slug}/alerts`} className="button secondary">
              <ShieldAlert size={15} /> Alert rules
            </Link>
          </div>
        }
      />

      <div className="panel response-filters-bar">
        <div className="filter-group">
          <SlidersHorizontal size={16} />
          <span className="filter-label">Status:</span>
          {(["all", "triage", "ready", "responding", "review", "closed", "dismissed"] as const).map(
            (st) => (
              <button
                key={st}
                type="button"
                className={`pill-button ${statusFilter === st ? "active" : ""}`}
                onClick={() => setStatusFilter(st)}
              >
                {st.toUpperCase()}
              </button>
            ),
          )}
        </div>

        <div className="filter-group">
          <Filter size={16} />
          <span className="filter-label">Severity:</span>
          {(["all", "critical", "warning", "advisory"] as const).map((sev) => (
            <button
              key={sev}
              type="button"
              className={`pill-button ${severityFilter === sev ? "active" : ""}`}
              onClick={() => setSeverityFilter(sev)}
            >
              {sev.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {casesApi.loading && !casesApi.data ? (
        <LoadingState label="Loading response episodes..." />
      ) : casesApi.error ? (
        <EmptyState error title={casesApi.error.code} body={casesApi.error.message} />
      ) : cases.length === 0 ? (
        <EmptyState
          title="No response episodes found"
          body="When threshold alerts or stale telemetry trigger rules with case automation, episodes appear here for operator verification."
          action={
            <Link to={`/app/${pilot.slug}/alerts`} className="button primary">
              Check alert rules
            </Link>
          }
        />
      ) : (
        <div className="response-grid">
          {cases.map((item) => {
            const activeStageIdx = getStageIndex(item.status, item.acknowledged_at);
            const isClosed = item.status === "closed";
            const isDismissed = item.status === "dismissed";

            return (
              <article key={item.id} className={`panel response-card ${item.severity}`}>
                <div className="response-card-header">
                  <div className="badge-row">
                    <span className={`severity-chip ${item.severity}`}>
                      {item.severity.toUpperCase()}
                    </span>
                    <StatusBadge status={item.status} />
                  </div>
                  <span className="case-rev">REV {item.revision}</span>
                </div>

                <h3 className="response-card-title">
                  {item.rule_name ? `Response: ${item.rule_name}` : item.mission_title || "Alert Response"}
                </h3>

                <div className="response-mini-stepper">
                  {STAGES.map((stage, idx) => {
                    const isDone = isClosed || idx < activeStageIdx;
                    const isCurrent = !isClosed && !isDismissed && idx === activeStageIdx;
                    return (
                      <div
                        key={stage}
                        className={`mini-step ${isDone ? "done" : ""} ${
                          isCurrent ? "current" : ""
                        }`}
                      >
                        <span className="step-dot" />
                        <span className="step-label">{stage}</span>
                      </div>
                    );
                  })}
                </div>

                <div className="response-card-metrics">
                  <div>
                    <span className="metric-label">Signals</span>
                    <strong>{item.alert_count} alert{item.alert_count !== 1 ? "s" : ""}</strong>
                  </div>
                  <div>
                    <span className="metric-label">Field route</span>
                    <strong>{item.route_run_id ? "Attached" : "Unassigned"}</strong>
                  </div>
                  <div>
                    <span className="metric-label">Updates</span>
                    <strong>{item.update_count} logged</strong>
                  </div>
                  <div>
                    <span className="metric-label">Opened</span>
                    <strong>{new Date(item.created_at).toLocaleDateString()}</strong>
                  </div>
                </div>

                {item.resolution_notes && (
                  <div className="resolution-preview">
                    <strong>Resolution:</strong> {item.resolution_notes}
                  </div>
                )}
                {item.dismissal_reason && (
                  <div className="dismissal-preview">
                    <strong>Dismissed:</strong> {item.dismissal_reason}
                  </div>
                )}

                <div className="response-card-footer">
                  <Link
                    to={`/app/${pilot.slug}/responses/${item.id}`}
                    className="button primary sm wide"
                  >
                    Open Response Episode <ArrowRight size={14} />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <EvidenceNote>
        Response Center enforces that automated alerts schedule missions without automated routes or field movement. Operators must verify terrain safety before mobilizing.
      </EvidenceNote>
    </div>
  );
}
