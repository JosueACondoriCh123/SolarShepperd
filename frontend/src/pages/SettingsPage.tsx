import { Bell, Database, Download, KeyRound, LogOut, Save, Trash2, UserRound } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiDelete, apiPatch } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../components/DataState";
import { PageHeader } from "../components/PageHeader";
import { clearPrivateDrafts, listSampleDrafts } from "../offlineStore";

export function SettingsPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState(auth.profile?.display_name || "");
  const [timezone, setTimezone] = useState(auth.profile?.timezone || "Africa/Nairobi");
  const [emailAlerts, setEmailAlerts] = useState(auth.profile?.notification_preferences.email ?? true);
  const [password, setPassword] = useState("");
  const [draftCount, setDraftCount] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const userId = auth.profile?.id || "";

  useEffect(() => {
    if (userId) void listSampleDrafts(userId).then((items) => setDraftCount(items.length));
  }, [userId]);

  if (auth.isGuest || !auth.profile) return <div className="page"><PageHeader kicker="13 / Account" title="Settings" description="Member profile and private device storage." /><EmptyState title="Guest session" body="Guest sessions have no private profile or offline workspace." /></div>;

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    try {
      await apiPatch("/me", { display_name: displayName, timezone, notification_preferences: { email: emailAlerts } });
      await auth.refreshProfile(); setMessage("Profile settings saved.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Settings could not be saved."); }
  };

  const exportDrafts = async () => {
    const drafts = await listSampleDrafts(userId);
    const manifest = drafts.map(({ photo, photos, ...item }) => ({
      ...item,
      photos: (photos || (photo ? [photo] : [])).map((image) => ({ name: image.name, type: image.type, size: image.size })),
    }));
    downloadBlob(new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }), "solarshepherd-offline-drafts.json");
    for (const draft of drafts) {
      const images = draft.photos || (draft.photo ? [draft.photo] : []);
      for (const image of images) downloadBlob(image, `sample-${draft.key.split(":").at(-1)}-${image.name}`);
    }
    setMessage("Draft manifest and attached photos exported. They remain on this device until you discard or sync them.");
  };

  const logout = async () => {
    if (draftCount > 0) { setError("Resolve private offline drafts first: sync them from Samples, export them, or discard them."); return; }
    await auth.signOut(); navigate("/");
  };

  return <div className="page">
    <PageHeader kicker="13 / Account" title="Settings" description="Manage your profile, credentials, notifications and private offline data." />
    {message && <p className="form-success notice-box">{message}</p>}{error && <p className="form-error notice-box">{error}</p>}
    <div className="settings-grid"><form className="panel settings-card" onSubmit={saveProfile}><div className="panel-header"><div><span className="panel-kicker">PROFILE</span><h2>Field identity</h2></div><UserRound /></div><label><span>Display name</span><input required minLength={2} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label><label><span>Timezone</span><input required value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label><label className="check-field"><input type="checkbox" checked={emailAlerts} onChange={(event) => setEmailAlerts(event.target.checked)} /><span><Bell size={14} /> Allow operational email alerts</span></label><button className="button primary"><Save size={15} /> Save profile</button></form>
      <section className="panel settings-card"><div className="panel-header"><div><span className="panel-kicker">SECURITY</span><h2>Password</h2></div><KeyRound /></div><label><span>New password</span><input minLength={8} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button className="button secondary" disabled={password.length < 8} onClick={async () => { await auth.updatePassword(password); setPassword(""); setMessage("Password updated."); }}>Update password</button></section>
      <section className="panel settings-card"><div className="panel-header"><div><span className="panel-kicker">THIS DEVICE</span><h2>Offline storage</h2></div><Database /></div><div className="readiness-number"><strong>{draftCount}</strong><span>private sample drafts</span></div><p>Drafts are separated by user and are never written to Cache Storage.</p><div className="form-actions"><button className="button secondary" disabled={!draftCount} onClick={() => void exportDrafts()}><Download size={15} /> Export</button><button className="button secondary" disabled={!draftCount} onClick={async () => { if (!window.confirm("Permanently discard offline drafts from this device?")) return; await clearPrivateDrafts(userId); setDraftCount(0); setMessage("Offline drafts discarded."); }}><Trash2 size={15} /> Discard</button></div></section>
      <section className="panel settings-card danger-zone"><div className="panel-header"><div><span className="panel-kicker">SESSION & ACCOUNT</span><h2>Access controls</h2></div><LogOut /></div><button className="button secondary" onClick={() => void logout()}><LogOut size={15} /> Log out</button><button className="button danger" onClick={async () => { if (!window.confirm("Delete your SolarShepherd account? This cannot be undone.")) return; await apiDelete("/me?confirm=true"); await clearPrivateDrafts(userId); await auth.signOut(); navigate("/"); }}><Trash2 size={15} /> Delete account</button></section></div>
  </div>;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
}
