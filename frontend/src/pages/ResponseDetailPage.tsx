import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Download,
  FileCheck2,
  FileJson,
  History,
  Image as ImageIcon,
  MapPin,
  Navigation,
  Radio,
  RotateCw,
  Send,
  ShieldAlert,
  X,
  XCircle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { apiDownload, apiGet, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { ResponseCaseDetail } from "../types";

const STAGES = [
  { key: "Detect", label: "1. Detect", desc: "Automated alert opened episode" },
  { key: "Verify", label: "2. Verify", desc: "Operator inspects & acknowledges" },
  { key: "Route", label: "3. Route", desc: "Terrain-safe route assigned" },
  { key: "Respond", label: "4. Respond", desc: "Field mission & updates" },
  { key: "Prove", label: "5. Prove", desc: "Audit report & closure" },
] as const;

export function ResponseDetailPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const { caseId } = useParams<{ caseId: string }>();

  const caseApi = useApi<ResponseCaseDetail>(
    () => apiGet(`/response-cases/${caseId}`),
    [caseId, pilot.slug],
    10_000,
  );

  // Modals and action states
  const [actionError, setActionError] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [showCloseModal, setShowCloseModal] = useState<boolean>(false);
  const [resolutionNotes, setResolutionNotes] = useState<string>("");
  const [showDismissModal, setShowDismissModal] = useState<boolean>(false);
  const [dismissReason, setDismissReason] = useState<string>("");

  // New update form states
  const [updateNotes, setUpdateNotes] = useState<string>("");
  const [updateLat, setUpdateLat] = useState<string>(String(pilot.center.latitude));
  const [updateLon, setUpdateLon] = useState<string>(String(pilot.center.longitude));
  const [selectedPhotos, setSelectedPhotos] = useState<File[]>([]);
  const [uploadingUpdate, setUploadingUpdate] = useState<boolean>(false);

  if (auth.isGuest) {
    return (
      <div className="page">
        <PageHeader
          kicker="09 / Response Center"
          title="Response Episode"
          description="Operational incident response workflow."
        />
        <EmptyState
          title="Operator account required"
          body="Response Center operations require authenticated field privileges."
          action={<Link className="button primary" to="/signup">Create account</Link>}
        />
      </div>
    );
  }

  const caseDetail = caseApi.data;

  // Action handlers
  const handleAcknowledge = async () => {
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/acknowledge`, {
        revision: caseDetail.revision,
      });
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to acknowledge episode.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleStart = async () => {
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/start`, {
        revision: caseDetail.revision,
      });
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to start response mission.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleComplete = async () => {
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/complete`, {
        revision: caseDetail.revision,
      });
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to complete mission.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetryReport = async () => {
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/report/retry`, {
        revision: caseDetail.revision,
      });
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to retry report.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = async (e: FormEvent) => {
    e.preventDefault();
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/close`, {
        resolution_notes: resolutionNotes,
        revision: caseDetail.revision,
      });
      setShowCloseModal(false);
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to close episode.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDismiss = async (e: FormEvent) => {
    e.preventDefault();
    if (!caseDetail) return;
    setActionError("");
    setSubmitting(true);
    try {
      await apiPost(`/response-cases/${caseDetail.id}/dismiss`, {
        reason: dismissReason,
        revision: caseDetail.revision,
      });
      setShowDismissModal(false);
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to dismiss episode.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateUpdate = async (e: FormEvent) => {
    e.preventDefault();
    if (!caseDetail) return;
    setActionError("");
    setUploadingUpdate(true);
    try {
      const updateRes = await apiPost<{ id: string }>(
        `/response-cases/${caseDetail.id}/updates`,
        {
          notes: updateNotes,
          latitude: Number(updateLat),
          longitude: Number(updateLon),
        },
      );

      // Upload photos if any
      for (const photo of selectedPhotos) {
        const formData = new FormData();
        formData.append("file", photo);
        const headers: Record<string, string> = {};
        const sessionToken = localStorage.getItem("solarshepherd-auth-session");
        if (sessionToken) {
          try {
            const parsed = JSON.parse(sessionToken);
            if (parsed.access_token) headers["Authorization"] = `Bearer ${parsed.access_token}`;
          } catch {
            // ignore
          }
        }
        await fetch(
          `/api/v1/response-updates/${updateRes.id}/attachments?pilot=${encodeURIComponent(
            pilot.slug,
          )}`,
          {
            method: "POST",
            headers,
            body: formData,
          },
        );
      }

      setUpdateNotes("");
      setSelectedPhotos([]);
      await caseApi.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to post update.");
    } finally {
      setUploadingUpdate(false);
    }
  };

  if (caseApi.loading && !caseDetail) {
    return (
      <div className="page">
        <LoadingState label="Loading episode details..." />
      </div>
    );
  }

  if (caseApi.error || !caseDetail) {
    return (
      <div className="page">
        <EmptyState
          error
          title={caseApi.error?.code || "Episode not found"}
          body={caseApi.error?.message || "The requested response episode could not be retrieved."}
          action={
            <Link to={`/app/${pilot.slug}/responses`} className="button primary">
              Return to Response Center
            </Link>
          }
        />
      </div>
    );
  }

  const next = caseDetail.next_action;
  const isClosed = caseDetail.status === "closed";
  const isDismissed = caseDetail.status === "dismissed";

  return (
    <div className="page">
      <PageHeader
        kicker="09 / Response Center"
        title={caseDetail.rule_name ? `Response: ${caseDetail.rule_name}` : "Response Episode"}
        description={`Episode ${caseDetail.id.slice(0, 8)} · Pilot ${pilot.name} (${pilot.slug.toUpperCase()})`}
        actions={
          <div className="header-controls">
            <Link to={`/app/${pilot.slug}/responses`} className="button secondary">
              ← All episodes
            </Link>
            <button
              className="button secondary"
              onClick={() => void caseApi.reload()}
              title="Refresh"
            >
              <RotateCw size={15} /> Refresh
            </button>
            {!isClosed && !isDismissed && (
              <button
                className="button secondary danger"
                onClick={() => setShowDismissModal(true)}
              >
                <XCircle size={15} /> Dismiss episode
              </button>
            )}
          </div>
        }
      />

      {actionError && <p className="form-error notice-box">{actionError}</p>}

      {/* Next Action Banner */}
      <section className={`panel next-action-banner stage-${next.stage.toLowerCase()}`}>
        <div className="next-action-info">
          <div className="banner-kicker-row">
            <span className="panel-kicker">NEXT OPERATIONAL ACTION</span>
            <span className="stage-pill">{next.stage.toUpperCase()} STAGE</span>
          </div>
          <h2>{next.label}</h2>
          <p>{next.description}</p>
        </div>

        <div className="next-action-controls">
          {next.action === "acknowledge" && (
            <button
              className="button primary"
              disabled={submitting}
              onClick={() => void handleAcknowledge()}
            >
              <CheckCircle2 size={16} /> Acknowledge Alert & Evidence
            </button>
          )}

          {next.action === "route" && (
            <Link
              to={`/app/${pilot.slug}/routes?response=${caseDetail.id}`}
              className="button primary"
            >
              <Navigation size={16} /> Open in Route Planner
            </Link>
          )}

          {next.action === "start" && (
            <button
              className="button primary"
              disabled={submitting}
              onClick={() => void handleStart()}
            >
              <Radio size={16} /> Start Response Mission
            </button>
          )}

          {next.action === "complete" && (
            <button
              className="button primary"
              disabled={submitting}
              onClick={() => void handleComplete()}
            >
              <CheckCircle2 size={16} /> Complete Mission & Generate Evidence
            </button>
          )}

          {next.action === "waiting_report" && (
            <div className="waiting-report-indicator">
              <RotateCw size={16} className="spin" />
              <span>Evidence report compiling...</span>
            </div>
          )}

          {next.action === "retry_report" && (
            <button
              className="button primary"
              disabled={submitting}
              onClick={() => void handleRetryReport()}
            >
              <RotateCw size={16} /> Retry Evidence Report
            </button>
          )}

          {next.action === "close" && (
            <button
              className="button primary"
              disabled={submitting}
              onClick={() => setShowCloseModal(true)}
            >
              <FileCheck2 size={16} /> Close Episode with Resolution Notes
            </button>
          )}
        </div>
      </section>

      {/* 5-Stage Stepper */}
      <div className="panel response-stepper">
        {STAGES.map((s, idx) => {
          let stageState = "upcoming";
          if (isClosed) {
            stageState = "done";
          } else if (isDismissed) {
            stageState = idx === 0 ? "done" : "cancelled";
          } else {
            const currentIdx = STAGES.findIndex((x) => x.key === next.stage);
            if (idx < currentIdx) stageState = "done";
            else if (idx === currentIdx) stageState = "active";
          }

          return (
            <div key={s.key} className={`stepper-node ${stageState}`}>
              <div className="node-badge">
                {stageState === "done" ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <span>{idx + 1}</span>
                )}
              </div>
              <div className="node-content">
                <strong>{s.key}</strong>
                <small>{s.desc}</small>
              </div>
            </div>
          );
        })}
      </div>

      <div className="response-detail-grid">
        {/* Left Column: Signals & Mission & Route */}
        <div className="detail-col">
          {/* Section 1: Signals Provenance */}
          <section className="panel detail-section">
            <div className="panel-header compact">
              <div>
                <span className="panel-kicker">STAGE 1 · DETECT</span>
                <h2>Originating Signals ({caseDetail.alerts.length})</h2>
              </div>
              <ShieldAlert size={18} />
            </div>

            <div className="alert-provenance-list">
              {caseDetail.alerts.map((a) => {
                const isForecast = a.kind === "forecast_threshold";
                return (
                  <article key={a.id} className="provenance-card">
                    <div className="provenance-top">
                      <span className={`signal-type-chip ${isForecast ? "forecast" : "observation"}`}>
                        {isForecast ? "Forecast (Projected)" : "Observation (Telemetry)"}
                      </span>
                      <span className={`severity-chip ${a.severity}`}>{a.severity}</span>
                      <span className="provenance-time">
                        {new Date(a.created_at).toLocaleString()}
                      </span>
                    </div>
                    <h4>{a.title}</h4>
                    <p>{a.message}</p>
                    {a.payload && Object.keys(a.payload).length > 0 && (
                      <pre className="provenance-payload">
                        {JSON.stringify(a.payload, null, 2)}
                      </pre>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          {/* Section 2: Mission & Route */}
          <section className="panel detail-section">
            <div className="panel-header compact">
              <div>
                <span className="panel-kicker">STAGES 2 & 3 · ROUTE & PLAN</span>
                <h2>Mission & Movement Route</h2>
              </div>
              <Navigation size={18} />
            </div>

            {caseDetail.mission ? (
              <div className="attached-mission-card">
                <div className="card-row">
                  <div>
                    <span className="metric-label">Mission title</span>
                    <strong>{caseDetail.mission.title}</strong>
                  </div>
                  <StatusBadge status={caseDetail.mission.status} />
                </div>
                <p>{caseDetail.mission.description}</p>
                <div className="card-meta-row">
                  <div>
                    <span className="metric-label">Scheduled start</span>
                    <span>
                      {caseDetail.mission.scheduled_start
                        ? new Date(caseDetail.mission.scheduled_start).toLocaleString()
                        : "None"}
                    </span>
                  </div>
                  <div>
                    <span className="metric-label">Scheduled end</span>
                    <span>
                      {caseDetail.mission.scheduled_end
                        ? new Date(caseDetail.mission.scheduled_end).toLocaleString()
                        : "None"}
                    </span>
                  </div>
                </div>

                <div className="attached-route-box">
                  {caseDetail.route ? (
                    <div>
                      <div className="route-attached-header">
                        <CheckCircle2 size={16} className="text-green" />
                        <strong>Verified terrain route attached</strong>
                      </div>
                      <div className="route-metrics">
                        <span>
                          Distance: {(caseDetail.route.total_distance_m / 1000).toFixed(2)} km
                        </span>
                        <span>
                          Est. Time: {(caseDetail.route.estimated_time_s / 3600).toFixed(1)} h
                        </span>
                        <span>Profile: {caseDetail.route.profile}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="no-route-box">
                      <AlertTriangle size={16} className="text-amber" />
                      <span>No terrain route attached yet.</span>
                      {caseDetail.status === "triage" && (
                        <Link
                          to={`/app/${pilot.slug}/routes?response=${caseDetail.id}`}
                          className="button secondary sm"
                        >
                          Calculate Route
                        </Link>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <p className="empty-inline">No mission assigned to this episode.</p>
            )}
          </section>
        </div>

        {/* Right Column: Evidence, Updates, Prove */}
        <div className="detail-col">
          {/* Section 3: Field Updates & Photos (Respond) */}
          <section className="panel detail-section">
            <div className="panel-header compact">
              <div>
                <span className="panel-kicker">STAGE 4 · RESPOND</span>
                <h2>Field Updates & Photo Evidence ({caseDetail.updates.length})</h2>
              </div>
              <Camera size={18} />
            </div>

            {/* Log Update Form */}
            {!isClosed && !isDismissed && (
              <form className="response-update-form" onSubmit={handleCreateUpdate}>
                <label>
                  <span>Field Observation Notes</span>
                  <textarea
                    required
                    placeholder="Document flock status, terrain conditions, water availability, or sensor inspect..."
                    value={updateNotes}
                    onChange={(e) => setUpdateNotes(e.target.value)}
                  />
                </label>

                <div className="coords-row">
                  <label>
                    <span>Latitude</span>
                    <input
                      required
                      type="number"
                      step="any"
                      value={updateLat}
                      onChange={(e) => setUpdateLat(e.target.value)}
                    />
                  </label>
                  <label>
                    <span>Longitude</span>
                    <input
                      required
                      type="number"
                      step="any"
                      value={updateLon}
                      onChange={(e) => setUpdateLon(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="button secondary sm reset-coords"
                    onClick={() => {
                      setUpdateLat(String(pilot.center.latitude));
                      setUpdateLon(String(pilot.center.longitude));
                    }}
                  >
                    Pilot Center
                  </button>
                </div>

                <label className="photo-upload-label">
                  <span>Attach Evidence Photos (max 3, stripped of EXIF, converted to WebP)</span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    onChange={(e) => {
                      if (e.target.files) {
                        const files = Array.from(e.target.files).slice(0, 3);
                        setSelectedPhotos(files);
                      }
                    }}
                  />
                </label>
                {selectedPhotos.length > 0 && (
                  <div className="selected-photos-preview">
                    {selectedPhotos.map((f, i) => (
                      <span key={i} className="photo-chip">
                        <ImageIcon size={12} /> {f.name} ({(f.size / 1024).toFixed(0)} KB)
                      </span>
                    ))}
                  </div>
                )}

                <button className="button primary sm" disabled={uploadingUpdate}>
                  <Send size={14} /> {uploadingUpdate ? "Submitting..." : "Log Field Update"}
                </button>
              </form>
            )}

            {/* Updates list */}
            <div className="updates-list">
              {caseDetail.updates.length === 0 ? (
                <p className="empty-inline">No field updates logged yet.</p>
              ) : (
                caseDetail.updates.map((u) => (
                  <article key={u.id} className="update-card">
                    <div className="update-top">
                      <span className="update-author">
                        {u.author_name || "Field Operator"}
                      </span>
                      <span className="update-coords">
                        <MapPin size={12} /> {u.latitude.toFixed(5)}, {u.longitude.toFixed(5)}
                      </span>
                      <span className="update-time">
                        {new Date(u.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="update-notes">{u.notes}</p>

                    {u.attachments && u.attachments.length > 0 && (
                      <div className="update-attachments">
                        {u.attachments.map((att) => (
                          <div key={att.id} className="attachment-chip">
                            <ImageIcon size={14} />
                            <span>{att.original_filename}</span>
                            <button
                              type="button"
                              className="link-download"
                              onClick={() =>
                                void apiDownload(
                                  `/response-attachments/${att.id}/download?pilot=${encodeURIComponent(
                                    pilot.slug,
                                  )}`,
                                  att.original_filename,
                                )
                              }
                            >
                              <Download size={12} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </article>
                ))
              )}
            </div>
          </section>

          {/* Section 4: Prove & Evidence Package */}
          <section className="panel detail-section">
            <div className="panel-header compact">
              <div>
                <span className="panel-kicker">STAGE 5 · PROVE</span>
                <h2>Evidence Package & Receipts</h2>
              </div>
              <FileCheck2 size={18} />
            </div>

            {caseDetail.report ? (
              <div className="report-package-box">
                <div className="report-status-row">
                  <div>
                    <span className="metric-label">Report ID</span>
                    <strong>{caseDetail.report.id.slice(0, 8)}...</strong>
                  </div>
                  <StatusBadge status={caseDetail.report.status} />
                </div>

                {caseDetail.report.status === "ready" && (
                  <div className="report-download-actions">
                    {caseDetail.report.downloads.pdf && (
                      <button
                        className="button secondary sm"
                        onClick={() =>
                          void apiDownload(
                            `/reports/${caseDetail.report!.id}/pdf?pilot=${encodeURIComponent(
                              pilot.slug,
                            )}`,
                            `solarshepherd-response-${caseDetail.id}.pdf`,
                          )
                        }
                      >
                        <Download size={14} /> Download Verified PDF
                      </button>
                    )}
                    {caseDetail.report.downloads.json && (
                      <button
                        className="button secondary sm"
                        onClick={() =>
                          void apiDownload(
                            `/reports/${caseDetail.report!.id}/json?pilot=${encodeURIComponent(
                              pilot.slug,
                            )}`,
                            `solarshepherd-response-${caseDetail.id}.json`,
                          )
                        }
                      >
                        <FileJson size={14} /> Download Evidence JSON
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="empty-inline">
                Evidence report compiles automatically upon mission completion.
              </p>
            )}

            {caseDetail.resolution_notes && (
              <div className="resolution-sealed-box">
                <strong>Resolution Notes:</strong>
                <p>{caseDetail.resolution_notes}</p>
                <small>
                  Closed at {new Date(caseDetail.closed_at!).toLocaleString()}
                </small>
              </div>
            )}

            {caseDetail.dismissal_reason && (
              <div className="dismissal-sealed-box">
                <strong>Dismissal Reason:</strong>
                <p>{caseDetail.dismissal_reason}</p>
                <small>
                  Dismissed at {new Date(caseDetail.dismissed_at!).toLocaleString()}
                </small>
              </div>
            )}
          </section>

          {/* Section 5: Audit History */}
          <section className="panel detail-section">
            <div className="panel-header compact">
              <div>
                <span className="panel-kicker">AUDIT RECORD</span>
                <h2>Lifecycle History ({caseDetail.timeline.length})</h2>
              </div>
              <History size={18} />
            </div>

            <div className="response-audit-timeline">
              {caseDetail.timeline.map((evt) => (
                <div key={evt.id} className="timeline-item">
                  <span className="timeline-item-badge">{evt.action.replace(/_/g, " ")}</span>
                  <div className="timeline-item-body">
                    <span className="timeline-item-time">
                      {new Date(evt.occurred_at).toLocaleString()}
                    </span>
                    {evt.details && Object.keys(evt.details).length > 0 && (
                      <pre className="timeline-item-details">
                        {JSON.stringify(evt.details, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {/* Close Episode Modal */}
      {showCloseModal && (
        <div className="timeline-overlay" onClick={() => setShowCloseModal(false)}>
          <div className="timeline-modal" onClick={(e) => e.stopPropagation()}>
            <div className="timeline-modal-header">
              <div>
                <span className="panel-kicker">STAGE 5 · SEAL RECORD</span>
                <h3>Close Response Episode</h3>
              </div>
              <button
                type="button"
                className="timeline-modal-close"
                onClick={() => setShowCloseModal(false)}
              >
                <X size={16} />
              </button>
            </div>
            <form className="modal-form" onSubmit={handleClose}>
              <p>
                Closing the episode requires a verified evidence report and permanent resolution
                notes documenting flock and site state.
              </p>
              <label>
                <span>Resolution Notes (required, min 3 chars)</span>
                <textarea
                  required
                  minLength={3}
                  rows={4}
                  placeholder="e.g., Flock moved to zone 2 shade canopy. Telemetry sensor re-anchored. Water refills verified."
                  value={resolutionNotes}
                  onChange={(e) => setResolutionNotes(e.target.value)}
                />
              </label>
              <div className="form-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setShowCloseModal(false)}
                >
                  Cancel
                </button>
                <button className="button primary" disabled={submitting}>
                  Confirm & Seal Episode
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Dismiss Episode Modal */}
      {showDismissModal && (
        <div className="timeline-overlay" onClick={() => setShowDismissModal(false)}>
          <div className="timeline-modal" onClick={(e) => e.stopPropagation()}>
            <div className="timeline-modal-header">
              <div>
                <span className="panel-kicker">DISMISSAL AUDIT</span>
                <h3>Dismiss Response Episode</h3>
              </div>
              <button
                type="button"
                className="timeline-modal-close"
                onClick={() => setShowDismissModal(false)}
              >
                <X size={16} />
              </button>
            </div>
            <form className="modal-form" onSubmit={handleDismiss}>
              <p>
                Dismissing an episode cancels any open response mission and records the rationale
                permanently in the audit log.
              </p>
              <label>
                <span>Dismissal Reason (required, min 3 chars)</span>
                <textarea
                  required
                  minLength={3}
                  rows={4}
                  placeholder="e.g., Sensor glitch confirmed by ground station; forecast superseded before mobilization..."
                  value={dismissReason}
                  onChange={(e) => setDismissReason(e.target.value)}
                />
              </label>
              <div className="form-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setShowDismissModal(false)}
                >
                  Cancel
                </button>
                <button className="button primary danger" disabled={submitting}>
                  Confirm Dismissal
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <EvidenceNote>
        Every alert in this episode is strictly delineated between advisory forecasts and real-time observations. Closing seals the audit manifest permanently.
      </EvidenceNote>
    </div>
  );
}
