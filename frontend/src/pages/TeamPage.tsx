import { History, ShieldCheck, Users } from "lucide-react";

import { apiGet, apiPatch } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { UserProfile } from "../auth/AuthContext";

export function TeamPage() {
  const { pilot } = usePilot();
  const members = useApi<{ data: UserProfile[]; count: number }>(() => apiGet("/admin/members"), []);
  const audit = useApi<{ data: { id: string; action: string; entity_type: string; entity_id: string | null; occurred_at: string }[]; count: number }>(() => apiGet("/admin/audit-events?limit=12"), []);
  return <div className="page">
    <PageHeader kicker="11 / Manage" title="Team" description={`Owner-only account status and audit-aware access management for ${pilot.name}.`} />
    <div className="owner-summary panel"><Users /><div><strong>{members.data?.count ?? "—"}</strong><span>registered pilot members</span></div><ShieldCheck /><p>Permissions are stored in Railway/Postgres, never user-editable identity metadata.</p></div>
    {members.loading && !members.data ? <LoadingState label="Loading members" /> : members.error ? <EmptyState error title={members.error.code} body={members.error.message} /> : members.data?.data.length ? <section className="member-list"><div className="table-row table-head"><span>Member</span><span>Timezone</span><span>Access</span><span>Last seen</span><span>Action</span></div>{members.data.data.map((member) => <article className="table-row panel" key={member.id}><div><strong>{member.display_name}</strong><small>{member.email || "Email unavailable"}</small></div><span>{member.timezone}</span><div><StatusBadge status={member.is_system_owner ? "owner" : member.status} /></div><span>{member.last_seen_at ? new Date(member.last_seen_at).toLocaleString() : "Never"}</span><button className="button secondary" disabled={member.is_system_owner} onClick={async () => { await apiPatch(`/admin/members/${member.id}`, { status: member.status === "active" ? "suspended" : "active" }); await members.reload(); }}>{member.status === "active" ? "Suspend" : "Restore"}</button></article>)}</section> : <EmptyState title="No members" body="Profiles are created after the first verified member session." />}
    <section className="panel audit-panel"><div className="panel-header"><div><span className="panel-kicker">RECENT AUDIT</span><h2>Administrative trail</h2></div><History /></div>{audit.data?.data.length ? <div className="audit-list">{audit.data.data.map((event) => <div key={event.id}><strong>{event.action.replaceAll("_", " ")}</strong><span>{event.entity_type} · {event.entity_id || "system"}</span><time>{new Date(event.occurred_at).toLocaleString()}</time></div>)}</div> : <p>No administrative actions recorded yet.</p>}</section>
  </div>;
}
