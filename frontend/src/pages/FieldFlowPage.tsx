import {
  Activity,
  ArrowRight,
  CheckCircle2,
  CloudSun,
  FileCheck2,
  FileText,
  Footprints,
  Map,
  Navigation,
  Plus,
  RefreshCw,
  Satellite,
  Sprout,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiGet, apiPatch, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { FieldFlowData, Mission } from "../types";

const stageIcons: Record<string, ReactNode> = {
  sense: <Activity size={19} />,
  read: <Map size={19} />,
  move: <Navigation size={19} />,
  act: <Footprints size={19} />,
  prove: <FileCheck2 size={19} />,
};

function formatMoment(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not available";
}

function formatAge(seconds: number | null) {
  if (seconds === null) return "No observation";
  if (seconds < 3_600) return `${Math.max(1, Math.round(seconds / 60))} min old`;
  if (seconds < 86_400) return `${(seconds / 3_600).toFixed(1)} h old`;
  return `${(seconds / 86_400).toFixed(1)} d old`;
}

export function FieldFlowPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const [searchParams, setSearchParams] = useSearchParams();
  const missionId = searchParams.get("mission") || "";
  const pathFor = (section: string) => `/app/${pilot.slug}/${section}`;
  const flow = useApi<FieldFlowData>(
    () => apiGet(`/field-flow${missionId ? `?mission_id=${encodeURIComponent(missionId)}` : ""}`),
    [missionId, pilot.slug],
    15_000,
  );
  const missions = useApi<{ data: Mission[]; count: number }>(
    () => apiGet("/missions"),
    [pilot.slug],
    undefined,
    !auth.isGuest,
  );
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({
    title: "",
    scheduled_start: "",
    herd_tlu: "",
    description: "",
  });

  const reload = async () => {
    await Promise.all([flow.reload(), auth.isGuest ? Promise.resolve() : missions.reload()]);
  };

  const createMission = async (event: FormEvent) => {
    event.preventDefault();
    if (!flow.data) return;
    setBusy(true);
    setError("");
    try {
      const mission = await apiPost<Mission>("/missions", {
        title: draft.title,
        description: draft.description,
        scheduled_start: draft.scheduled_start
          ? new Date(draft.scheduled_start).toISOString()
          : null,
        scheduled_end: null,
        route_run_id: flow.data.route?.id || null,
        herd_tlu: draft.herd_tlu ? Number(draft.herd_tlu) : null,
        notes: "Created from the Field Decision Loop.",
      });
      setCreating(false);
      setDraft({ title: "", scheduled_start: "", herd_tlu: "", description: "" });
      setMessage("Mission created and connected to the current evidence chain.");
      setSearchParams({ mission: mission.id });
      await missions.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The mission could not be created.");
    } finally {
      setBusy(false);
    }
  };

  const updateMission = async (updates: Record<string, unknown>, success: string) => {
    if (!flow.data?.mission) return;
    setBusy(true);
    setError("");
    try {
      await apiPatch(`/missions/${flow.data.mission.id}`, {
        ...updates,
        revision: flow.data.mission.revision,
      });
      setMessage(success);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The mission could not be updated.");
    } finally {
      setBusy(false);
    }
  };

  const generateReport = async () => {
    if (!flow.data?.mission) return;
    setBusy(true);
    setError("");
    try {
      await apiPost("/reports", { mission_id: flow.data.mission.id });
      setMessage("Evidence package queued. This view will update when it is ready.");
      await flow.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The report could not be generated.");
    } finally {
      setBusy(false);
    }
  };

  if (flow.loading && !flow.data) {
    return <div className="page"><LoadingState label="Building the field decision loop" /></div>;
  }
  if (flow.error || !flow.data) {
    return <div className="page"><EmptyState error title={flow.error?.code || "FLOW_UNAVAILABLE"} body={flow.error?.message || "The evidence workflow could not be assembled."} /></div>;
  }

  const data = flow.data;
  const activeMissionId = missionId || data.mission?.id || "";
  const action = data.next_action;
  let primaryAction: ReactNode;
  if (action.key === "create_mission") {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => setCreating(true)}><Plus size={16} /> {action.label}</button>;
  } else if (action.key === "attach_route" && data.route) {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => void updateMission({ route_run_id: data.route?.id }, "Saved route attached to the mission.")}><Navigation size={16} /> {action.label}</button>;
  } else if (action.key === "plan_mission") {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => void updateMission({ status: "planned" }, "Mission marked as planned.")}><CheckCircle2 size={16} /> {action.label}</button>;
  } else if (action.key === "start_mission") {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => void updateMission({ status: "active" }, "Mission started and timestamped.")}><Footprints size={16} /> {action.label}</button>;
  } else if (action.key === "complete_mission") {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => void updateMission({ status: "completed" }, "Mission completed and ready for reporting.")}><CheckCircle2 size={16} /> {action.label}</button>;
  } else if (action.key === "generate_report") {
    primaryAction = <button className="button primary" disabled={busy} onClick={() => void generateReport()}><FileText size={16} /> {action.label}</button>;
  } else {
    const query = action.section === "samples" && data.mission ? `?mission=${data.mission.id}` : "";
    primaryAction = <Link className="button primary" to={`${pathFor(action.section)}${query}`}>{action.label}<ArrowRight size={16} /></Link>;
  }

  return <div className="page field-flow-page">
    <PageHeader
      kicker={`01 / ${pilot.name} field decision loop`}
      title="From evidence to accountable action."
      description="One auditable path connects observed conditions, landscape, movement, field work and a versioned scientific receipt."
      actions={<button className="button secondary" disabled={flow.loading} onClick={() => void reload()}><RefreshCw size={15} /> Refresh evidence</button>}
    />

    {auth.isGuest && <div className="guest-banner"><strong>Shared evidence mode</strong><span>Explore the decision chain. Sign up to persist routes, missions, samples and reports.</span></div>}
    {message && <p className="form-success notice-box" role="status">{message}</p>}
    {error && <p className="form-error notice-box" role="alert">{error}</p>}

    {!auth.isGuest && <section className="flow-mission-switcher panel">
      <div><span className="panel-kicker">WORKING RECORD</span><strong>{data.mission ? data.mission.title : "No mission selected"}</strong></div>
      <label><span>Mission</span><select value={activeMissionId} onChange={(event) => setSearchParams(event.target.value ? { mission: event.target.value } : {})}><option value="">Recommended current mission</option>{missions.data?.data.map((mission) => <option key={mission.id} value={mission.id}>{mission.title} · {mission.status}</option>)}</select></label>
      <button className="button secondary" onClick={() => setCreating((value) => !value)}><Plus size={15} /> Quick mission</button>
    </section>}

    {creating && <form className="panel flow-quick-mission" onSubmit={createMission}>
      <div className="panel-header"><div><span className="panel-kicker">QUICK BRIEF</span><h2>Create the operational record</h2></div><Footprints /></div>
      <div className="form-grid">
        <label><span>Mission title</span><input required minLength={2} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder={`${pilot.name} field assessment`} /></label>
        <label><span>Scheduled start</span><input type="datetime-local" value={draft.scheduled_start} onChange={(event) => setDraft({ ...draft, scheduled_start: event.target.value })} /></label>
        <label><span>Herd size · TLU</span><input type="number" min="0.01" value={draft.herd_tlu} onChange={(event) => setDraft({ ...draft, herd_tlu: event.target.value })} placeholder="Recorded only" /></label>
        <label className="wide"><span>Purpose</span><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="What should this mission verify in the field?" /></label>
      </div>
      <div className="flow-form-note">{data.route ? `Route “${data.route.name}” will be attached.` : "No route will be invented. You can add one after terrain routing succeeds."}</div>
      <div className="form-actions"><button type="button" className="button secondary" onClick={() => setCreating(false)}>Cancel</button><button className="button primary" disabled={busy}>{busy ? "Creating…" : "Create mission"}</button></div>
    </form>}

    <section className="field-flow-rail" aria-label="Field decision stages">
      {data.stages.map((stage, index) => <article className={`flow-stage ${stage.status}`} key={stage.key}>
        <div className="flow-stage-index"><span>{String(index + 1).padStart(2, "0")}</span>{stageIcons[stage.key]}</div>
        <div><div className="flow-stage-heading"><h2>{stage.label}</h2><StatusBadge status={stage.status} /></div><p>{stage.summary}</p><small>{stage.evidence_at ? `Evidence · ${formatMoment(stage.evidence_at)}` : "No evidence timestamp"}</small></div>
      </article>)}
    </section>

    <section className="flow-next panel">
      <div className="flow-next-number">NEXT</div>
      <div><span className="panel-kicker">DETERMINISTIC RECOMMENDATION</span><h2>{action.label}</h2><p>{action.reason}</p></div>
      {primaryAction}
    </section>

    <div className="flow-evidence-grid">
      <article className="panel flow-evidence-card">
        <div className="flow-evidence-icon weather"><CloudSun /></div>
        <div><span className="panel-kicker">SENSE / OBSERVED</span><h3>Ground signal</h3></div>
        <StatusBadge status={data.evidence.telemetry.status} />
        <strong>{formatAge(data.evidence.telemetry.age_seconds)}</strong>
        <p>{data.evidence.telemetry.source || "No observational source"}</p>
        <small>{data.evidence.telemetry.station_id || "No station"} · {formatMoment(data.evidence.telemetry.observed_at)}</small>
        {data.evidence.telemetry.quality_flags.length > 0 && <div className="flow-flags">{data.evidence.telemetry.quality_flags.map((flag) => <span key={flag}>{flag.replaceAll("_", " ")}</span>)}</div>}
        <Link to={pathFor("telemetry")}>Inspect observations <ArrowRight size={13} /></Link>
      </article>

      <article className="panel flow-evidence-card">
        <div className="flow-evidence-icon satellite"><Satellite /></div>
        <div><span className="panel-kicker">READ / LANDSCAPE</span><h3>Sentinel surface</h3></div>
        <StatusBadge status={data.evidence.scene.status} />
        <strong>{data.evidence.scene.valid_fraction == null ? "Coverage unavailable" : `${Math.round(data.evidence.scene.valid_fraction * 100)}% valid pixels`}</strong>
        <p>{data.evidence.scene.source || "No persisted scene"}</p>
        <small>{data.evidence.scene.id || "No scene ID"} · {formatMoment(data.evidence.scene.acquired_at)}</small>
        <Link to={pathFor("landscape")}>Read landscape <ArrowRight size={13} /></Link>
      </article>

      <article className="panel flow-evidence-card">
        <div className="flow-evidence-icon route"><Navigation /></div>
        <div><span className="panel-kicker">MOVE / ROUTE</span><h3>{data.route?.name || "No saved route"}</h3></div>
        <StatusBadge status={data.route?.attached ? "attached" : data.route ? "available" : "blocked"} />
        <strong>{data.route?.total_distance_m != null ? `${(data.route.total_distance_m / 1_000).toFixed(2)} km` : "Terrain route required"}</strong>
        <p>{data.route ? `${data.route.profile.replaceAll("_", " ")} profile` : "No distance or cost has been inferred."}</p>
        <small>{data.route ? formatMoment(data.route.requested_at) : "No route timestamp"}</small>
        <Link to={pathFor("routes")}>Open route planner <ArrowRight size={13} /></Link>
      </article>

      <article className="panel flow-evidence-card">
        <div className="flow-evidence-icon sample"><Sprout /></div>
        <div><span className="panel-kicker">PROVE / FIELD EVIDENCE</span><h3>{data.samples.total} mission samples</h3></div>
        <StatusBadge status={data.samples.approved ? "reviewed" : data.samples.total ? "review required" : "optional"} />
        <strong>{data.samples.approved} approved</strong>
        <p>{data.samples.pending_review} pending · {data.samples.draft} drafts · {data.samples.rejected} rejected</p>
        <small>Biomass remains locked until scientific calibration is approved.</small>
        <Link to={`${pathFor("samples")}${data.mission ? `?mission=${data.mission.id}` : ""}`}>Capture evidence <ArrowRight size={13} /></Link>
      </article>
    </div>

    {data.mission && <section className="panel flow-mission-passport">
      <div><span className="panel-kicker">MISSION PASSPORT</span><h2>{data.mission.title}</h2><p>{data.mission.description || "No purpose recorded."}</p></div>
      <dl>
        <div><dt>Status</dt><dd><StatusBadge status={data.mission.status} /></dd></div>
        <div><dt>Schedule</dt><dd>{formatMoment(data.mission.scheduled_start)}</dd></div>
        <div><dt>Route</dt><dd>{data.mission.route_run_id ? "Attached" : "Not attached"}</dd></div>
        <div><dt>Herd context</dt><dd>{data.mission.herd_tlu ? `${data.mission.herd_tlu} TLU · not applied to GCH` : "Not recorded"}</dd></div>
        <div><dt>Revision</dt><dd>{data.mission.revision}</dd></div>
        <div><dt>Evidence package</dt><dd>{data.report?.status || "Not generated"}</dd></div>
      </dl>
      <div className="flow-passport-actions"><Link className="button secondary" to={`${pathFor("missions")}`}>Full mission record</Link><Link className="button secondary" to={`${pathFor("reports")}?mission=${data.mission.id}`}>Reports</Link></div>
    </section>}

    <EvidenceNote>The recommendation is a transparent state machine over persisted evidence. It is not a language-model prediction and never invents weather, biomass, capacity or route inputs.</EvidenceNote>
  </div>;
}
