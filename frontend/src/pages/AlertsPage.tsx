import { Bell, BellRing, Check, Plus, ToggleLeft, ToggleRight, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { apiDelete, apiGet, apiPatch, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import type { AlertRule, UserAlert } from "../types";

const metricLabels: Record<string, string> = {
  temperature_c: "Temperature · °C",
  precipitation_probability_pct: "Rain probability · %",
  precipitation_mm: "Precipitation · mm",
  uv_index: "UV index",
  wind_speed_m_s: "Wind speed · m/s",
  wind_gust_m_s: "Wind gust · m/s",
};

export function AlertsPage() {
  const auth = useAuth();
  const alerts = useApi<{ data: UserAlert[]; count: number }>(() => apiGet("/alerts"), [], 30_000);
  const rules = useApi<{ data: AlertRule[]; count: number }>(() => apiGet("/alert-rules"), []);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ name: "High UV forecast", kind: "forecast_threshold", metric: "uv_index", comparator: ">=", threshold: "8", lookahead_hours: "24", email: false });

  if (auth.isGuest) return <div className="page"><PageHeader kicker="08 / Attention" title="Alerts" description="Personal rules are available to verified members." /><EmptyState title="Guest sessions have no alert inbox" body="Create an account to configure transparent weather thresholds and mission reminders." action={<Link className="button primary" to="/signup">Create account</Link>} /></div>;

  const create = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    try {
      const thresholdRule = ["forecast_threshold", "telemetry_stale"].includes(draft.kind);
      await apiPost("/alert-rules", {
        name: draft.name,
        kind: draft.kind,
        metric: draft.kind === "forecast_threshold" ? draft.metric : null,
        comparator: thresholdRule ? draft.comparator : null,
        threshold: thresholdRule ? Number(draft.threshold) : null,
        lookahead_hours: Number(draft.lookahead_hours),
        cooldown_minutes: 180,
        channels: draft.email ? ["in_app", "email"] : ["in_app"],
      });
      setShowForm(false); await rules.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The rule could not be saved."); }
  };

  return <div className="page">
    <PageHeader kicker="08 / Attention" title="Alerts" description="Define your own operational thresholds. SolarShepherd does not hide scientific cut-offs in the product." actions={<button className="button primary" onClick={() => setShowForm((value) => !value)}><Plus size={15} /> New rule</button>} />
    {showForm && <form className="panel mission-form" onSubmit={create}><div className="panel-header"><div><span className="panel-kicker">EXPLICIT RULE</span><h2>Choose what deserves attention</h2></div><BellRing /></div><div className="form-grid"><label><span>Name</span><input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label><span>Rule type</span><select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}><option value="forecast_threshold">Forecast threshold</option><option value="telemetry_stale">Telemetry freshness</option><option value="mission_reminder">Mission reminder</option></select></label>{draft.kind === "forecast_threshold" && <label><span>Metric</span><select value={draft.metric} onChange={(event) => setDraft({ ...draft, metric: event.target.value })}>{Object.entries(metricLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>}{["forecast_threshold", "telemetry_stale"].includes(draft.kind) && <><label><span>Comparison</span><select value={draft.comparator} onChange={(event) => setDraft({ ...draft, comparator: event.target.value })}><option>&gt;=</option><option>&gt;</option><option>&lt;=</option><option>&lt;</option></select></label><label><span>{draft.kind === "telemetry_stale" ? "Age · hours" : "Threshold"}</span><input required type="number" step="any" value={draft.threshold} onChange={(event) => setDraft({ ...draft, threshold: event.target.value })} /></label></>}<label><span>Look-ahead · hours</span><input required min="1" max="168" type="number" value={draft.lookahead_hours} onChange={(event) => setDraft({ ...draft, lookahead_hours: event.target.value })} /></label><label className="check-field"><input type="checkbox" checked={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.checked })} /><span>Also send email</span></label></div><div className="form-actions"><button type="button" className="button secondary" onClick={() => setShowForm(false)}>Cancel</button><button className="button primary">Save rule</button></div></form>}
    {error && <p className="form-error notice-box">{error}</p>}
    <div className="alerts-layout"><section><div className="section-title"><div><span className="panel-kicker">INBOX</span><h2>Recent signals</h2></div><Bell /></div>{alerts.loading && !alerts.data ? <LoadingState /> : alerts.data?.data.length ? <div className="alert-list">{alerts.data.data.map((alert) => <article className={`panel alert-card ${alert.acknowledged_at ? "acknowledged" : ""}`} key={alert.id}><StatusBadge status={alert.severity} /><div><h3>{alert.title}</h3><p>{alert.message}</p><small>{new Date(alert.created_at).toLocaleString()}</small></div>{!alert.acknowledged_at && <button aria-label="Acknowledge alert" onClick={async () => { await apiPost(`/alerts/${alert.id}/acknowledge`, {}); await alerts.reload(); }}><Check /></button>}</article>)}</div> : <EmptyState title="Inbox clear" body="Triggered rules and sample review outcomes will appear here." />}</section><section><div className="section-title"><div><span className="panel-kicker">RULES</span><h2>Your thresholds</h2></div></div>{rules.loading && !rules.data ? <LoadingState /> : rules.data?.data.length ? <div className="rule-list">{rules.data.data.map((rule) => <article className="panel rule-card" key={rule.id}><div><h3>{rule.name}</h3><p>{rule.kind.replaceAll("_", " ")}{rule.threshold != null ? ` · ${rule.comparator} ${rule.threshold}` : ""}</p><small>{rule.channels.join(" + ")}</small></div><button aria-label={rule.enabled ? "Disable rule" : "Enable rule"} onClick={async () => { await apiPatch(`/alert-rules/${rule.id}`, { enabled: !rule.enabled }); await rules.reload(); }}>{rule.enabled ? <ToggleRight /> : <ToggleLeft />}</button><button aria-label="Delete rule" onClick={async () => { await apiDelete(`/alert-rules/${rule.id}`); await rules.reload(); }}><Trash2 /></button></article>)}</div> : <EmptyState title="No alert rules" body="Create a transparent threshold for forecast, freshness or mission timing." />}</section></div>
    <EvidenceNote>Forecast alerts are advisory. They are not observations and do not alter route costs or carrying-capacity calculations.</EvidenceNote>
  </div>;
}
