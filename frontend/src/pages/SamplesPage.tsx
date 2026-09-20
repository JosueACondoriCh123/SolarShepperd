import { Camera, Check, CloudUpload, LocateFixed, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { apiGet, apiPost, apiUpload } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { useApi } from "../hooks/useApi";
import { deleteSampleDraft, listSampleDrafts, saveSampleDraft, type OfflineSampleDraft } from "../offlineStore";
import { usePilot } from "../pilot/PilotContext";
import type { Mission, SampleSubmission } from "../types";

const localNow = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16);

export function SamplesPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const [searchParams] = useSearchParams();
  const queryMissionId = searchParams.get("mission") || "";

  const samples = useApi<{ data: SampleSubmission[]; count: number }>(() => apiGet("/sample-submissions"), [], 30_000);
  const missions = useApi<{ data: Mission[]; count: number }>(() => apiGet("/missions"), []);
  const [offlineDrafts, setOfflineDrafts] = useState<OfflineSampleDraft[]>([]);
  const [showForm, setShowForm] = useState(Boolean(queryMissionId));
  const [photos, setPhotos] = useState<File[]>([]);
  const [photoPreviews, setPhotoPreviews] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({
    mission_id: queryMissionId,
    external_reference: "",
    sampled_at: localNow(),
    latitude: "",
    longitude: "",
    dry_matter_kg_ha: "",
    method: "clipped quadrat",
    quadrat_area_m2: "0.25",
  });
  const userId = auth.profile?.id || "";

  useEffect(() => {
    if (queryMissionId) {
      setDraft((prev) => ({ ...prev, mission_id: queryMissionId }));
      setShowForm(true);
    }
  }, [queryMissionId]);

  useEffect(() => {
    const urls = photos.map((file) => URL.createObjectURL(file));
    setPhotoPreviews(urls);
    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [photos]);

  const loadDrafts = useCallback(async () => {
    setOfflineDrafts(await listSampleDrafts(userId, pilot.slug));
  }, [pilot.slug, userId]);
  useEffect(() => { if (!auth.isGuest) void loadDrafts(); }, [auth.isGuest, loadDrafts]);

  if (auth.isGuest) return <div className="page"><PageHeader kicker="06 / Field evidence" title="Samples" description="Georeferenced samples support future calibration." /><EmptyState title="Members collect evidence" body="Create an account before storing GPS coordinates or field photographs." action={<Link className="button primary" to="/signup">Create account</Link>} /></div>;
  if (!auth.profile) return <div className="page"><PageHeader kicker="06 / Field evidence" title="Samples" description="Georeferenced samples support future calibration." /><LoadingState /></div>;

  const locate = () => navigator.geolocation.getCurrentPosition((position) => setDraft((value) => ({ ...value, latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) })), () => setError("Location permission was not granted."));
  const payload = () => ({
    mission_id: draft.mission_id || null,
    external_reference: draft.external_reference || null,
    sampled_at: new Date(draft.sampled_at).toISOString(),
    latitude: Number(draft.latitude),
    longitude: Number(draft.longitude),
    dry_matter_kg_ha: Number(draft.dry_matter_kg_ha),
    method: draft.method,
    quadrat_area_m2: Number(draft.quadrat_area_m2),
  });

  const send = async (body: Record<string, unknown>, images: File[] = []) => {
    const created = await apiPost<SampleSubmission>("/sample-submissions", body);
    for (const image of images.slice(0, 3)) {
      await apiUpload(`/sample-submissions/${created.id}/attachments`, image);
    }
    return created;
  };

  const removePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, i) => i !== index));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setMessage("");
    const body = payload();
    try {
      if (!navigator.onLine) throw new Error("offline");
      await send(body, photos);
      setMessage("Sample saved as a draft. Review it before submitting.");
      setPhotos([]); setShowForm(false); await samples.reload();
    } catch (reason) {
      if (!navigator.onLine || (reason instanceof Error && reason.message === "offline")) {
        const key = `${userId}:${pilot.slug}:${crypto.randomUUID()}`;
        await saveSampleDraft({ key, userId, pilotSlug: pilot.slug, createdAt: new Date().toISOString(), payload: body, photos });
        setMessage("Stored securely on this device. Sync it when connectivity returns.");
        setPhotos([]); setShowForm(false); await loadDrafts();
      } else setError(reason instanceof Error ? reason.message : "Sample could not be saved.");
    }
  };

  const syncSingle = async (item: OfflineSampleDraft) => {
    setError(""); setMessage("");
    try {
      const images = item.photos || (item.photo ? [item.photo] : []);
      await send(item.payload, images);
      await deleteSampleDraft(item.key);
      setMessage("Offline sample synced successfully.");
    } catch (reason) {
      const errMsg = reason instanceof Error ? reason.message : "Sync failed";
      await saveSampleDraft({
        ...item,
        lastError: errMsg,
        retryCount: (item.retryCount || 0) + 1,
        retriedAt: new Date().toISOString(),
      });
      setError(`Sync failed for draft: ${errMsg}`);
    }
    await loadDrafts();
    await samples.reload();
  };

  const discardDraft = async (key: string) => {
    await deleteSampleDraft(key);
    await loadDrafts();
    setMessage("Offline draft discarded.");
  };

  const syncAll = async () => {
    setError(""); setMessage("");
    for (const item of offlineDrafts) {
      try {
        const images = item.photos || (item.photo ? [item.photo] : []);
        await send(item.payload, images);
        await deleteSampleDraft(item.key);
      } catch (reason) {
        const errMsg = reason instanceof Error ? reason.message : "Draft sync failed.";
        await saveSampleDraft({
          ...item,
          lastError: errMsg,
          retryCount: (item.retryCount || 0) + 1,
          retriedAt: new Date().toISOString(),
        });
        setError(`Draft sync interrupted: ${errMsg}`);
        break;
      }
    }
    await loadDrafts();
    await samples.reload();
  };

  const submitForReview = async (item: SampleSubmission) => { await apiPost(`/sample-submissions/${item.id}/submit`, {}); await samples.reload(); };
  const review = async (item: SampleSubmission, decision: "approved" | "rejected") => { const notes = decision === "rejected" ? window.prompt("Reason for rejection") || "" : "Evidence reviewed by system owner."; if (decision === "rejected" && !notes) return; await apiPost(`/admin/sample-submissions/${item.id}/review`, { decision, notes }); await samples.reload(); };

  return <div className="page">
    <PageHeader kicker="06 / Field evidence" title="Samples" description="Capture genuine dry-matter evidence, preserve it offline and submit it for scientific review." actions={<button className="button primary" onClick={() => setShowForm((value) => !value)}><Plus size={16} /> Capture sample</button>} />
    {offlineDrafts.length > 0 && <div className="offline-queue panel" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "14px", width: "100%" }}>
        <CloudUpload />
        <div style={{ flex: 1 }}>
          <strong>{offlineDrafts.length} private offline draft{offlineDrafts.length === 1 ? "" : "s"}</strong>
          <span>Only visible to this account on this device.</span>
        </div>
        <button className="button primary" disabled={!navigator.onLine} onClick={() => void syncAll()}><RefreshCw size={15} /> Sync all</button>
      </div>
      <div className="offline-draft-list">
        {offlineDrafts.map((item) => {
          const photoCount = item.photos?.length || (item.photo ? 1 : 0);
          const dm = item.payload.dry_matter_kg_ha;
          const dt = String(item.payload.sampled_at || item.createdAt);
          return (
            <div key={item.key} className="offline-draft-card">
              <div className="offline-draft-info">
                <strong>{dm ? `${dm} kg/ha` : "Sample draft"}</strong>
                <span>Sampled: {new Date(dt).toLocaleString()} · Photos: {photoCount}</span>
                {item.lastError && <span className="offline-draft-error">Error: {item.lastError} (retried {item.retryCount || 0}x)</span>}
              </div>
              <div className="offline-draft-actions">
                <button type="button" className="primary" disabled={!navigator.onLine} onClick={() => void syncSingle(item)} title="Retry syncing this draft">
                  <RefreshCw size={12} /> Retry
                </button>
                <button type="button" className="danger" onClick={() => void discardDraft(item.key)} title="Discard draft">
                  <Trash2 size={12} /> Discard
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>}
    {showForm && <form className="panel mission-form" onSubmit={submit}><div className="panel-header"><div><span className="panel-kicker">MOBILE CAPTURE</span><h2>Record dry matter</h2></div><Camera /></div><div className="form-grid"><label><span>Mission (optional)</span><select value={draft.mission_id} onChange={(event) => setDraft({ ...draft, mission_id: event.target.value })}><option value="">No mission attached</option>{missions.data?.data.map((m) => <option key={m.id} value={m.id}>{m.title} ({m.status})</option>)}</select></label><label><span>External reference</span><input value={draft.external_reference} onChange={(event) => setDraft({ ...draft, external_reference: event.target.value })} /></label><label><span>Sampled at</span><input required type="datetime-local" value={draft.sampled_at} onChange={(event) => setDraft({ ...draft, sampled_at: event.target.value })} /></label><label><span>Latitude</span><input required type="number" step="any" value={draft.latitude} onChange={(event) => setDraft({ ...draft, latitude: event.target.value })} /></label><label><span>Longitude</span><input required type="number" step="any" value={draft.longitude} onChange={(event) => setDraft({ ...draft, longitude: event.target.value })} /></label><label><span>Dry matter · kg/ha</span><input required min="0.01" type="number" step="any" value={draft.dry_matter_kg_ha} onChange={(event) => setDraft({ ...draft, dry_matter_kg_ha: event.target.value })} /></label><label><span>Quadrat area · m²</span><input required min="0.01" type="number" step="any" value={draft.quadrat_area_m2} onChange={(event) => setDraft({ ...draft, quadrat_area_m2: event.target.value })} /></label><label className="wide"><span>Method</span><input required value={draft.method} onChange={(event) => setDraft({ ...draft, method: event.target.value })} /></label><label className="wide"><span>Evidence photos · optional, maximum 3</span><input type="file" multiple accept="image/jpeg,image/png,image/webp" onChange={(event) => { const selected = Array.from(event.target.files || []); if (photos.length + selected.length > 3) setError("Select at most three evidence photos in total."); const combined = [...photos, ...selected].slice(0, 3); setPhotos(combined); event.target.value = ""; }} />{photoPreviews.length > 0 && <div className="photo-previews">{photoPreviews.map((url, idx) => <div key={url} className="photo-preview-item"><img src={url} alt={`Evidence photo ${idx + 1}`} /><button type="button" className="photo-preview-remove" title="Remove photo" onClick={() => removePhoto(idx)}><X size={12} /></button></div>)}</div>}</label></div><div className="form-actions"><button type="button" className="button secondary" onClick={locate}><LocateFixed size={15} /> Use GPS</button><button className="button primary">Save draft</button></div></form>}
    {error && <p className="form-error notice-box">{error}</p>}{message && <p className="form-success notice-box">{message}</p>}
    {samples.loading && !samples.data ? <LoadingState /> : samples.error ? <EmptyState error title={samples.error.code} body={samples.error.message} /> : samples.data?.data.length ? <section className="sample-list">{samples.data.data.map((item) => {
      const attachedMission = missions.data?.data.find((m) => m.id === item.mission_id);
      return <article className="panel sample-record" key={item.id}><div>{attachedMission && <span className="sample-mission-badge">Mission: {attachedMission.title}</span>}<StatusBadge status={item.status} /><h2>{item.sample_code}</h2><p>{new Date(item.sampled_at).toLocaleString()} · {item.latitude.toFixed(5)}, {item.longitude.toFixed(5)}</p></div><dl><div><dt>Dry matter</dt><dd>{item.dry_matter_kg_ha} kg/ha</dd></div><div><dt>Method</dt><dd>{item.method}</dd></div><div><dt>Quadrat</dt><dd>{item.quadrat_area_m2} m²</dd></div><div><dt>Photos</dt><dd>{item.attachment_count}</dd></div><div><dt>Mission</dt><dd>{attachedMission ? attachedMission.title : item.mission_id ? "Attached" : "None"}</dd></div></dl>{item.review_notes && <p className="review-note">Review: {item.review_notes}</p>}<div className="sample-actions">{["draft", "rejected"].includes(item.status) && <button className="button primary" onClick={() => void submitForReview(item)}><CloudUpload size={15} /> Submit for review</button>}{auth.isOwner && item.status === "pending_review" && <><button className="button primary" onClick={() => void review(item, "approved")}><Check size={15} /> Approve</button><button className="button secondary" onClick={() => void review(item, "rejected")}><X size={15} /> Reject</button></>}</div></article>;
    })}</section> : <EmptyState title="No submitted samples" body="Capture a sample online or store it locally until connectivity returns." />}
    <EvidenceNote>Approval registers the observation for calibration coverage only. It does not train or activate a biomass model automatically.</EvidenceNote>
  </div>;
}
