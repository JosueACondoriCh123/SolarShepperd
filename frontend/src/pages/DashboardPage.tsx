import { Activity, Bell, CloudSun, Map, Navigation, Plus, Sprout } from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { apiGet } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { DashboardData } from "../types";

export function DashboardPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const pathFor = (section: string) => `/app/${pilot.slug}/${section}`;
  const dashboard = useApi<DashboardData>(() => apiGet("/dashboard"), [], 60_000);
  if (dashboard.loading && !dashboard.data) return <div className="page"><LoadingState label="Assembling the operational picture" /></div>;
  if (dashboard.error || !dashboard.data) return <div className="page"><EmptyState error title={dashboard.error?.code || "DASHBOARD_UNAVAILABLE"} body={dashboard.error?.message || "The dashboard could not be loaded."} /></div>;
  const data = dashboard.data;
  return <div className="page">
    <PageHeader kicker={`00 / ${pilot.name} overview`} title={`Good field work starts here${auth.profile?.display_name ? `, ${auth.profile.display_name}` : ""}.`} description={auth.isGuest ? `Guest mode shows shared ${pilot.name} evidence. Create an account to save missions, routes and samples.` : `Your ${pilot.name} missions, environmental evidence and outstanding actions in one place.`} actions={auth.isGuest ? <Link className="button primary" to="/signup">Create account</Link> : <Link className="button primary" to={pathFor("missions")}><Plus size={16} /> New mission</Link>} />
    {auth.isGuest && <div className="guest-banner"><strong>Guest session</strong><span>Read-only pilot access · no private work is stored</span></div>}
    <section className="dashboard-kpis">
      <article className="panel"><Activity /><span>Latest telemetry</span><strong>{data.telemetry_latest_at ? new Date(data.telemetry_latest_at).toLocaleTimeString() : "Unavailable"}</strong><small>{data.telemetry_latest_at ? new Date(data.telemetry_latest_at).toLocaleDateString() : "No station observation"}</small></article>
      <article className="panel"><CloudSun /><span>Forecast horizon</span><strong>{data.forecast_valid_to ? new Date(data.forecast_valid_to).toLocaleDateString() : "Unavailable"}</strong><small>{data.forecast_generated_at ? `Generated ${new Date(data.forecast_generated_at).toLocaleString()}` : "No forecast run"}</small></article>
      <article className="panel"><Map /><span>Latest Sentinel scene</span><strong>{data.scene ? new Date(data.scene.acquired_at).toLocaleDateString() : "Unavailable"}</strong><small>{data.scene?.cloud_cover_pct != null ? `${data.scene.cloud_cover_pct.toFixed(1)}% cloud` : "No complete scene"}</small></article>
      <article className="panel"><Bell /><span>Unread alerts</span><strong>{data.unread_alerts}</strong><small>{auth.isGuest ? "Sign up to create rules" : "User-defined thresholds only"}</small></article>
    </section>
    <div className="dashboard-grid">
      <section className="panel action-panel"><div className="panel-header"><div><span className="panel-kicker">NEXT FIELD ACTION</span><h2>{data.active_mission?.title || "No active mission"}</h2></div><Navigation /></div>{data.active_mission ? <><StatusBadge status={data.active_mission.status} /><p>{data.active_mission.description || "No mission description."}</p><dl className="inspection-list"><div><dt>Start</dt><dd>{data.active_mission.scheduled_start ? new Date(data.active_mission.scheduled_start).toLocaleString() : "Not scheduled"}</dd></div><div><dt>Route</dt><dd>{data.active_mission.route_run_id ? "Attached" : "Not attached"}</dd></div><div><dt>Herd</dt><dd>{data.active_mission.herd_tlu ? `${data.active_mission.herd_tlu} TLU · recorded only` : "Not recorded"}</dd></div></dl><Link className="button primary" to={pathFor("missions")}>Open mission</Link></> : <><p>Create a mission to connect a route, schedule, notes and field evidence.</p>{!auth.isGuest && <Link className="button primary" to={pathFor("missions")}>Plan a mission</Link>}</>}</section>
      <section className="panel action-panel"><div className="panel-header"><div><span className="panel-kicker">SCIENTIFIC READINESS</span><h2>Calibration remains locked</h2></div><Sprout /></div><div className="readiness-number"><strong>{data.pending_samples}</strong><span>samples awaiting review</span></div><p>Only reviewed, georeferenced dry-matter samples can enter the calibration registry.</p><Link className="button secondary" to={pathFor("capacity")}>Review requirements</Link></section>
      <section className="panel quick-actions"><span className="panel-kicker">QUICK ACCESS</span><h2>Move from signal to evidence</h2><div><Link to={pathFor("telemetry")}><Activity />Check station</Link><Link to={pathFor("landscape")}><Map />Inspect landscape</Link><Link to={pathFor("routes")}><Navigation />Plan route</Link><Link to={pathFor("samples")}><Sprout />Capture sample</Link></div></section>
    </div>
    <EvidenceNote>The dashboard summarizes source timestamps and your own workflow. It never converts missing evidence into an estimate.</EvidenceNote>
  </div>;
}
