import {
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Copy,
  Edit3,
  FileText,
  History,
  Navigation,
  Plus,
  Radio,
  X,
  XCircle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { apiGet, apiPatch, apiPost } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { Mission, TimelineEvent } from "../types";

interface SavedRoute { id: string; name: string; requested_at: string; total_distance_m: number; profile: string }

const toLocalInput = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

export function MissionsPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const [searchParams] = useSearchParams();
  const initialRouteId = searchParams.get("route") || "";
  const missions = useApi<{ data: Mission[]; count: number }>(() => apiGet("/missions"), [], 30_000);
  const routes = useApi<{ data: SavedRoute[]; count: number }>(() => apiGet("/routes"), [], 60_000);
  const [creating, setCreating] = useState(Boolean(initialRouteId));
  const [editingMission, setEditingMission] = useState<Mission | null>(null);
  const [timelineMission, setTimelineMission] = useState<Mission | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ title: "", description: "", scheduled_start: "", scheduled_end: "", route_run_id: initialRouteId, herd_tlu: "", notes: "" });
  const [editDraft, setEditDraft] = useState({ title: "", description: "", scheduled_start: "", scheduled_end: "", route_run_id: "", herd_tlu: "", notes: "" });

  if (auth.isGuest) return <div className="page"><PageHeader kicker="03 / Field work" title="Missions" description="Missions connect routes, schedules and evidence." /><EmptyState title="Create an account to plan missions" body="Guest mode remains read-only so anonymous work cannot enter the operational record." action={<Link className="button primary" to="/signup">Create account</Link>} /></div>;

  const create = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    try {
      await apiPost<Mission>("/missions", {
        title: draft.title,
        description: draft.description,
        scheduled_start: draft.scheduled_start ? new Date(draft.scheduled_start).toISOString() : null,
        scheduled_end: draft.scheduled_end ? new Date(draft.scheduled_end).toISOString() : null,
        route_run_id: draft.route_run_id || null,
        herd_tlu: draft.herd_tlu ? Number(draft.herd_tlu) : null,
        notes: draft.notes,
      });
      setDraft({ title: "", description: "", scheduled_start: "", scheduled_end: "", route_run_id: "", herd_tlu: "", notes: "" });
      setCreating(false); await missions.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Mission could not be created."); }
  };

  const startEdit = (mission: Mission) => {
    setEditingMission(mission);
    setEditDraft({
      title: mission.title,
      description: mission.description || "",
      scheduled_start: toLocalInput(mission.scheduled_start),
      scheduled_end: toLocalInput(mission.scheduled_end),
      route_run_id: mission.route_run_id || "",
      herd_tlu: mission.herd_tlu !== null && mission.herd_tlu !== undefined ? String(mission.herd_tlu) : "",
      notes: mission.notes || "",
    });
  };

  const saveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingMission) return;
    setError("");
    try {
      await apiPatch<Mission>(`/missions/${editingMission.id}`, {
        title: editDraft.title,
        description: editDraft.description,
        scheduled_start: editDraft.scheduled_start ? new Date(editDraft.scheduled_start).toISOString() : null,
        scheduled_end: editDraft.scheduled_end ? new Date(editDraft.scheduled_end).toISOString() : null,
        route_run_id: editDraft.route_run_id || null,
        herd_tlu: editDraft.herd_tlu ? Number(editDraft.herd_tlu) : null,
        notes: editDraft.notes,
        revision: editingMission.revision,
      });
      setEditingMission(null);
      await missions.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Mission could not be updated.");
    }
  };

  const duplicate = async (mission: Mission) => {
    setError("");
    try {
      await apiPost<Mission>(`/missions/${mission.id}/duplicate`, {});
      await missions.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to duplicate mission.");
    }
  };

  const openTimeline = async (mission: Mission) => {
    setTimelineMission(mission);
    setLoadingTimeline(true);
    try {
      const res = await apiGet<TimelineEvent[]>(`/missions/${mission.id}/timeline`);
      setTimelineEvents(res);
    } catch {
      setTimelineEvents([]);
    } finally {
      setLoadingTimeline(false);
    }
  };

  const transition = async (mission: Mission, status: Mission["status"]) => {
    await apiPatch(`/missions/${mission.id}`, { status, revision: mission.revision });
    await missions.reload();
  };

  return <div className="page">
    <PageHeader kicker="03 / Field work" title="Missions" description="Connect a route, schedule and field evidence without turning herd size into an uncalibrated capacity estimate." actions={<button className="button primary" onClick={() => setCreating((value) => !value)}><Plus size={16} /> New mission</button>} />
    {error && <p className="form-error notice-box">{error}</p>}
    {creating && <form className="panel mission-form" onSubmit={create}><div className="panel-header"><div><span className="panel-kicker">MISSION BRIEF</span><h2>Plan field work</h2></div><ClipboardList /></div><div className="form-grid"><label><span>Title</span><input required value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label><label><span>Saved route</span><select value={draft.route_run_id} onChange={(event) => setDraft({ ...draft, route_run_id: event.target.value })}><option value="">No route attached</option>{routes.data?.data.map((route) => <option key={route.id} value={route.id}>{route.name} · {(route.total_distance_m / 1000).toFixed(1)} km</option>)}</select></label><label><span>Starts</span><input type="datetime-local" value={draft.scheduled_start} onChange={(event) => setDraft({ ...draft, scheduled_start: event.target.value })} /></label><label><span>Ends</span><input type="datetime-local" value={draft.scheduled_end} onChange={(event) => setDraft({ ...draft, scheduled_end: event.target.value })} /></label><label><span>Herd size · TLU</span><input type="number" min="0" placeholder="Recorded, not applied" value={draft.herd_tlu} onChange={(event) => setDraft({ ...draft, herd_tlu: event.target.value })} /></label><label className="wide"><span>Description</span><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label><label className="wide"><span>Field notes</span><textarea value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} /></label></div><div className="form-actions"><button type="button" className="button secondary" onClick={() => setCreating(false)}>Cancel</button><button className="button primary">Save mission</button></div></form>}
    {editingMission && <form className="panel mission-form" onSubmit={saveEdit}><div className="panel-header"><div><span className="panel-kicker">EDIT MISSION · REV {editingMission.revision}</span><h2>{editingMission.title}</h2></div><Edit3 /></div><div className="form-grid"><label><span>Title</span><input required value={editDraft.title} onChange={(event) => setEditDraft({ ...editDraft, title: event.target.value })} /></label><label><span>Saved route</span><select value={editDraft.route_run_id} onChange={(event) => setEditDraft({ ...editDraft, route_run_id: event.target.value })}><option value="">No route attached</option>{routes.data?.data.map((route) => <option key={route.id} value={route.id}>{route.name} · {(route.total_distance_m / 1000).toFixed(1)} km</option>)}</select></label><label><span>Starts</span><input type="datetime-local" value={editDraft.scheduled_start} onChange={(event) => setEditDraft({ ...editDraft, scheduled_start: event.target.value })} /></label><label><span>Ends</span><input type="datetime-local" value={editDraft.scheduled_end} onChange={(event) => setEditDraft({ ...editDraft, scheduled_end: event.target.value })} /></label><label><span>Herd size · TLU</span><input type="number" min="0" placeholder="Recorded, not applied" value={editDraft.herd_tlu} onChange={(event) => setEditDraft({ ...editDraft, herd_tlu: event.target.value })} /></label><label className="wide"><span>Description</span><textarea value={editDraft.description} onChange={(event) => setEditDraft({ ...editDraft, description: event.target.value })} /></label><label className="wide"><span>Field notes</span><textarea value={editDraft.notes} onChange={(event) => setEditDraft({ ...editDraft, notes: event.target.value })} /></label></div><div className="form-actions"><button type="button" className="button secondary" onClick={() => setEditingMission(null)}>Cancel</button><button className="button primary">Update mission</button></div></form>}
    {missions.loading && !missions.data ? <LoadingState /> : missions.error ? <EmptyState error title={missions.error.code} body={missions.error.message} /> : missions.data?.data.length ? <section className="mission-grid">{missions.data.data.map((mission) => <article className="panel mission-card" key={mission.id}><div className="mission-card-top"><StatusBadge status={mission.status} /><span>REV {mission.revision}</span></div><h2>{mission.title}</h2><p>{mission.description || "No description supplied."}</p><dl><div><dt><CalendarDays />Schedule</dt><dd>{mission.scheduled_start ? new Date(mission.scheduled_start).toLocaleString() : "Not scheduled"}</dd></div><div><dt><Navigation />Route</dt><dd>{mission.route_run_id ? "Evidence route attached" : "Not attached"}</dd></div><div><dt><Radio />Herd</dt><dd>{mission.herd_tlu ? `${mission.herd_tlu} TLU · not applied to GCH` : "Not recorded"}</dd></div><div><dt><FileText />Samples</dt><dd>{mission.sample_count ?? 0} attached</dd></div></dl><div className="mission-actions">{mission.status === "draft" && <button onClick={() => void transition(mission, "planned")}><CalendarDays /> Plan</button>}{mission.status === "planned" && <button onClick={() => void transition(mission, "active")}><Radio /> Start</button>}{mission.status === "active" && <button onClick={() => void transition(mission, "completed")}><CheckCircle2 /> Complete</button>}{!(["completed", "cancelled"] as string[]).includes(mission.status) && <button onClick={() => void transition(mission, "cancelled")}><XCircle /> Cancel</button>}<button onClick={() => startEdit(mission)}><Edit3 /> Edit</button><button onClick={() => void duplicate(mission)}><Copy /> Duplicate</button><button onClick={() => void openTimeline(mission)}><History /> Timeline</button></div><div className="mission-links"><Link className="mission-link-button" to={`/app/${pilot.slug}/samples?mission=${mission.id}`}><Plus size={11} /> Attach sample</Link><Link className="mission-link-button" to={`/app/${pilot.slug}/reports?mission=${mission.id}`}><FileText size={11} /> Generate report</Link></div></article>)}</section> : <EmptyState title="No missions yet" body="Create the first mission and attach a saved evidence route when available." />}
    {timelineMission && <div className="timeline-overlay" onClick={() => setTimelineMission(null)}><div className="timeline-modal" onClick={(e) => e.stopPropagation()}><div className="timeline-modal-header"><div><span className="panel-kicker">AUDIT RECORD</span><h3>{timelineMission.title} · History</h3></div><button type="button" className="timeline-modal-close" onClick={() => setTimelineMission(null)} title="Close timeline"><X size={16} /></button></div><div className="timeline-content">{loadingTimeline ? <LoadingState label="Loading audit history..." /> : timelineEvents.length === 0 ? <div className="timeline-empty">No audit events recorded for this mission.</div> : timelineEvents.map((evt) => <div key={evt.id} className="timeline-item"><span className="timeline-item-badge">{evt.action.replace(/_/g, " ")}</span><div className="timeline-item-body"><span className="timeline-item-time">{new Date(evt.occurred_at).toLocaleString()}</span>{evt.details && Object.keys(evt.details).length > 0 && <pre className="timeline-item-details">{JSON.stringify(evt.details, null, 2)}</pre>}</div></div>)}</div></div></div>}
    <EvidenceNote>Missions organize operational evidence. Herd size is recorded for context but cannot unlock GCH while calibration is pending.</EvidenceNote>
  </div>;
}
