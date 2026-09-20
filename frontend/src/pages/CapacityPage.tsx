import { Beaker, CheckCircle2, ClipboardPlus, Download, FlaskConical, LocateFixed, LockKeyhole, Scale, Sprout } from "lucide-react";
import { useState } from "react";

import { API_BASE, apiGet } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { ScienceMap } from "../components/ScienceMap";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type { CalibrationCoverage, CalibrationStatus } from "../types";

interface DraftSample {
  sample_id: string;
  sampled_at_with_timezone: string;
  latitude: number;
  longitude: number;
  dry_matter_kg_ha: number;
  method: string;
  quadrat_area_m2: number;
}

const localNow = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16);

export function CapacityPage() {
  const { pilot } = usePilot();
  const draftStorageKey = `solarshepherd-sample-drafts:${pilot.slug}`;
  const { data, error, loading, reload } = useApi<CalibrationStatus>(() => apiGet("/calibration/status"), [], 120_000);
  const coverage = useApi<CalibrationCoverage>(() => apiGet("/calibration/samples/coverage"), [], 120_000);
  const [drafts, setDrafts] = useState<DraftSample[]>(() => {
    try { return JSON.parse(localStorage.getItem(draftStorageKey) || "[]") as DraftSample[]; }
    catch { return []; }
  });
  const [draft, setDraft] = useState({ sample_id: "", sampled_at: localNow(), latitude: "", longitude: "", dry_matter_kg_ha: "", method: "clipped quadrat", quadrat_area_m2: "0.25" });

  const locate = () => navigator.geolocation?.getCurrentPosition((position) => setDraft((value) => ({ ...value, latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) })));
  const saveDraft = () => {
    const next: DraftSample = {
      sample_id: draft.sample_id.trim(),
      sampled_at_with_timezone: new Date(draft.sampled_at).toISOString(),
      latitude: Number(draft.latitude),
      longitude: Number(draft.longitude),
      dry_matter_kg_ha: Number(draft.dry_matter_kg_ha),
      method: draft.method.trim(),
      quadrat_area_m2: Number(draft.quadrat_area_m2),
    };
    if (!next.sample_id || !next.method || !Number.isFinite(next.latitude) || !Number.isFinite(next.longitude) || next.dry_matter_kg_ha <= 0 || next.quadrat_area_m2 <= 0) return;
    const values = [...drafts.filter((item) => item.sample_id !== next.sample_id), next];
    setDrafts(values);
    localStorage.setItem(draftStorageKey, JSON.stringify(values));
    setDraft((value) => ({ ...value, sample_id: "", dry_matter_kg_ha: "" }));
  };
  const exportDrafts = () => {
    const header = "sample_id,sampled_at_with_timezone,latitude,longitude,dry_matter_kg_ha,method,quadrat_area_m2";
    const rows = drafts.map((item) => [item.sample_id, item.sampled_at_with_timezone, item.latitude, item.longitude, item.dry_matter_kg_ha, `"${item.method.replaceAll('"', '""')}"`, item.quadrat_area_m2].join(","));
    const url = URL.createObjectURL(new Blob([[header, ...rows].join("\n")], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "solarshepherd-field-samples.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page">
      <PageHeader
        kicker="04 / Grazing sustainability"
        title="Carrying capacity"
        description="Dry-matter and grazing-horizon outputs stay locked until field calibration can defend them."
        actions={<a className="button secondary" href={`${API_BASE}/calibration/samples/template.csv`}><Download size={16} /> CSV template</a>}
      />

      {loading && !data ? <LoadingState label="Checking calibration registry" /> : error ? (
        <EmptyState error title={error.code} body={error.message} action={<button onClick={() => void reload()}>Try again</button>} />
      ) : data && (
        <>
          <section className="calibration-hero panel">
            <div className="calibration-lock"><LockKeyhole size={34} /></div>
            <div className="calibration-copy">
              <StatusBadge status={data.status} />
              <h2>No biomass estimate is being displayed</h2>
              <p>{data.message} This prevents a vegetation index from being misrepresented as kilograms of dry matter.</p>
            </div>
            <div className="sample-counter"><span>Validated samples</span><strong>{data.sample_count}</strong><small>local observations</small></div>
          </section>

          <div className="capacity-grid">
            <section className="panel readiness-panel">
              <div className="panel-header">
                <div><span className="panel-kicker">CALIBRATION CONTRACT</span><h2>Required field evidence</h2></div>
                <FlaskConical size={20} />
              </div>
              <div className="contract-list">
                {data.required_fields.map((field, index) => (
                  <div key={field}><span>{String(index + 1).padStart(2, "0")}</span><code>{field}</code><small>Required</small></div>
                ))}
              </div>
            </section>

            <section className="panel methodology-panel">
              <div className="panel-header">
                <div><span className="panel-kicker">ACTIVATION GATE</span><h2>From sample to decision</h2></div>
                <Beaker size={20} />
              </div>
              <ol className="method-steps">
                <li><span><Sprout size={18} /></span><div><strong>Collect dry matter</strong><p>Georeferenced, dated quadrat measurements with documented method.</p></div></li>
                <li><span><Scale size={18} /></span><div><strong>Match Earth observation</strong><p>Pair field samples to cloud-free Sentinel-2 acquisitions.</p></div></li>
                <li><span><CheckCircle2 size={18} /></span><div><strong>Validate before activation</strong><p>Hold out plots or dates and publish error metrics with the model version.</p></div></li>
              </ol>
            </section>

            <section className="panel capacity-formula">
              <span className="panel-kicker">FUTURE GCH EQUATION</span>
              <h2>Usable forage ÷ daily herd demand</h2>
              <div className="formula">
                <span>calibrated kg DM/ha × actual cell area × required utilization factor</span>
                <hr />
                <span>TLU count × 6.25 kg DM/day</span>
              </div>
              <p>No utilization factor receives a hidden default. It must be supplied and documented for the operating context.</p>
            </section>

            <section className="panel sample-capture-panel">
              <div className="panel-header"><div><span className="panel-kicker">FIELD QUEUE</span><h2>Capture a real sample</h2></div><ClipboardPlus size={20} /></div>
              <p className="data-note">Stored only on this device until you export and submit the protected CSV import.</p>
              <div className="sample-form">
                <label><span>Sample ID</span><input value={draft.sample_id} onChange={(event) => setDraft({ ...draft, sample_id: event.target.value })} /></label>
                <label><span>Sampled at</span><input type="datetime-local" value={draft.sampled_at} onChange={(event) => setDraft({ ...draft, sampled_at: event.target.value })} /></label>
                <label><span>Latitude</span><input type="number" step="any" value={draft.latitude} onChange={(event) => setDraft({ ...draft, latitude: event.target.value })} /></label>
                <label><span>Longitude</span><input type="number" step="any" value={draft.longitude} onChange={(event) => setDraft({ ...draft, longitude: event.target.value })} /></label>
                <label><span>Dry matter kg/ha</span><input type="number" min="0" value={draft.dry_matter_kg_ha} onChange={(event) => setDraft({ ...draft, dry_matter_kg_ha: event.target.value })} /></label>
                <label><span>Quadrat area m²</span><input type="number" min="0" step="0.01" value={draft.quadrat_area_m2} onChange={(event) => setDraft({ ...draft, quadrat_area_m2: event.target.value })} /></label>
                <label className="wide"><span>Method</span><input value={draft.method} onChange={(event) => setDraft({ ...draft, method: event.target.value })} /></label>
              </div>
              <div className="capture-actions"><button className="button secondary" onClick={locate}><LocateFixed size={16} /> Use GPS</button><button className="button primary" onClick={saveDraft}>Queue sample</button><button className="button secondary" disabled={!drafts.length} onClick={exportDrafts}><Download size={16} /> Export {drafts.length}</button></div>
            </section>

            <section className="panel sample-coverage-panel">
              <div className="panel-header"><div><span className="panel-kicker">REGISTERED EVIDENCE</span><h2>Sample coverage</h2></div><StatusBadge status={coverage.data?.meta.sample_count ? "collecting" : "awaiting samples"} /></div>
              <div className="coverage-stats"><div><span>Imported</span><strong>{coverage.data?.meta.sample_count || 0}</strong></div><div><span>Scene matched</span><strong>{coverage.data?.meta.scene_matched_count || 0}</strong></div><div><span>Pending match</span><strong>{coverage.data?.meta.unmatched_count || 0}</strong></div></div>
              <div className="sample-map"><ScienceMap pilot={pilot} samples={coverage.data || null} /></div>
            </section>
          </div>
          <EvidenceNote>Imported samples can document spatial and scene coverage, but only a separately validated model can unlock biomass and GCH.</EvidenceNote>
        </>
      )}
    </div>
  );
}
