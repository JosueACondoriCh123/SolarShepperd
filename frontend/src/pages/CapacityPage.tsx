import {
  Beaker,
  Calculator,
  CheckCircle2,
  ClipboardPlus,
  Download,
  FlaskConical,
  LocateFixed,
  LockKeyhole,
  Scale,
  Sparkles,
  Sprout,
  Unlock,
} from "lucide-react";
import { useCallback, useState } from "react";

import { API_BASE, apiGet, apiPost } from "../api";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { ScienceMap } from "../components/ScienceMap";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type {
  CalibrationCoverage,
  CalibrationModelSummary,
  CalibrationStatus,
  GchCalculationResult,
} from "../types";

interface DraftSample {
  sample_id: string;
  sampled_at_with_timezone: string;
  latitude: number;
  longitude: number;
  dry_matter_kg_ha: number;
  method: string;
  quadrat_area_m2: number;
}

const localNow = () =>
  new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);

const CALIBRATION_STEPS = [
  { id: "collect", label: "01 / Collect", title: "Dry matter quadrats", desc: "Georeferenced field cuts" },
  { id: "match", label: "02 / Match", title: "Satellite pairing", desc: "Sentinel-2 ±5 day match" },
  { id: "fit", label: "03 / Fit", title: "Empirical regression", desc: "Ordinary least squares" },
  { id: "validate", label: "04 / Validate", title: "Scientific defense", desc: "R², RMSE, and MAE checks" },
  { id: "activate", label: "05 / Activate", title: "Biomass & GCH gate", desc: "Operational lock release" },
];

export function CapacityPage() {
  const auth = useAuth();
  const { pilot } = usePilot();
  const draftStorageKey = `solarshepherd-sample-drafts:${pilot.slug}`;

  const { data, error, loading, reload } = useApi<CalibrationStatus>(
    () => apiGet("/calibration/status"),
    [pilot.slug],
    120_000,
  );
  const coverage = useApi<CalibrationCoverage>(
    () => apiGet("/calibration/samples/coverage"),
    [pilot.slug],
    120_000,
  );
  const models = useApi<{ models: CalibrationModelSummary[]; active_model: CalibrationModelSummary | null }>(
    () => apiGet("/calibration/models"),
    [pilot.slug],
    60_000,
  );

  // Model fitting form state
  const [isFittingOpen, setIsFittingOpen] = useState(false);
  const [fitAlgorithm, setFitAlgorithm] = useState("linear_ols");
  const [fitNotes, setFitNotes] = useState("");
  const [fitting, setFitting] = useState(false);
  const [fitError, setFitError] = useState<string | null>(null);

  // Model activation state
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Grazing Capacity Horizon calculator state
  const [herdTlu, setHerdTlu] = useState(250);
  const [utilizationFactor, setUtilizationFactor] = useState(0.4);
  const [gchResult, setGchResult] = useState<GchCalculationResult | null>(null);
  const [calculatingGch, setCalculatingGch] = useState(false);
  const [gchError, setGchError] = useState<string | null>(null);

  // Offline draft samples state
  const [drafts, setDrafts] = useState<DraftSample[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(draftStorageKey) || "[]") as DraftSample[];
    } catch {
      return [];
    }
  });
  const [draft, setDraft] = useState({
    sample_id: "",
    sampled_at: localNow(),
    latitude: "",
    longitude: "",
    dry_matter_kg_ha: "",
    method: "clipped quadrat",
    quadrat_area_m2: "0.25",
  });

  const locate = () =>
    navigator.geolocation?.getCurrentPosition((position) =>
      setDraft((value) => ({
        ...value,
        latitude: position.coords.latitude.toFixed(6),
        longitude: position.coords.longitude.toFixed(6),
      })),
    );

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
    if (
      !next.sample_id ||
      !next.method ||
      !Number.isFinite(next.latitude) ||
      !Number.isFinite(next.longitude) ||
      next.dry_matter_kg_ha <= 0 ||
      next.quadrat_area_m2 <= 0
    )
      return;
    const values = [...drafts.filter((item) => item.sample_id !== next.sample_id), next];
    setDrafts(values);
    localStorage.setItem(draftStorageKey, JSON.stringify(values));
    setDraft((value) => ({ ...value, sample_id: "", dry_matter_kg_ha: "" }));
  };

  const exportDrafts = () => {
    const header =
      "sample_id,sampled_at_with_timezone,latitude,longitude,dry_matter_kg_ha,method,quadrat_area_m2";
    const rows = drafts.map((item) =>
      [
        item.sample_id,
        item.sampled_at_with_timezone,
        item.latitude,
        item.longitude,
        item.dry_matter_kg_ha,
        `"${item.method.replaceAll('"', '""')}"`,
        item.quadrat_area_m2,
      ].join(","),
    );
    const url = URL.createObjectURL(new Blob([[header, ...rows].join("\n")], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "solarshepherd-field-samples.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleFitModel = async () => {
    setFitting(true);
    setFitError(null);
    try {
      await apiPost("/calibration/models/fit", {
        pilot_slug: pilot.slug,
        algorithm: fitAlgorithm,
        notes: fitNotes || "Empirical linear least-squares regression",
      });
      setIsFittingOpen(false);
      setFitNotes("");
      setActionMessage("Candidate model successfully fitted and added to calibration registry.");
      await Promise.all([reload(), models.reload()]);
    } catch (err: unknown) {
      setFitError(err instanceof Error ? err.message : "Failed to fit candidate model.");
    } finally {
      setFitting(false);
    }
  };

  const handleActivateModel = async (modelId: string) => {
    setActivatingId(modelId);
    setActionMessage(null);
    try {
      await apiPost(`/calibration/models/${modelId}/activate`, {
        notes: `Activated via web console by ${auth.profile?.display_name || "operator"}`,
      });
      setActionMessage("Model activated successfully. Biomass and GCH layer unlocked.");
      await Promise.all([reload(), models.reload()]);
    } catch (err: unknown) {
      setActionMessage(err instanceof Error ? `Activation failed: ${err.message}` : "Activation failed.");
    } finally {
      setActivatingId(null);
    }
  };

  const handleCalculateGch = useCallback(async () => {
    setCalculatingGch(true);
    setGchError(null);
    try {
      const res = await apiPost<GchCalculationResult>("/calibration/gch/calculate", {
        herd_tlu: Number(herdTlu),
        utilization_factor: Number(utilizationFactor),
        pilot_slug: pilot.slug,
      });
      setGchResult(res);
    } catch (err: unknown) {
      setGchError(err instanceof Error ? err.message : "Calculation failed.");
    } finally {
      setCalculatingGch(false);
    }
  }, [herdTlu, pilot.slug, utilizationFactor]);

  const matchedCount =
    data?.matched_sample_count ?? coverage.data?.meta.scene_matched_count ?? 0;
  const candidateModels = (models.data?.models || []).filter((m) => m.status === "candidate");
  const isReady = data?.status === "READY";
  const currentStepIndex = isReady
    ? 4
    : candidateModels.length > 0
    ? 3
    : matchedCount >= 3
    ? 2
    : (data?.sample_count ?? 0) > 0
    ? 1
    : 0;

  return (
    <div className="page">
      <PageHeader
        kicker="04 / Grazing sustainability"
        title="Carrying capacity"
        description="Dry-matter and grazing-horizon outputs stay locked until field calibration can defend them."
        actions={
          <a className="button secondary" href={`${API_BASE}/calibration/samples/template.csv`}>
            <Download size={16} /> CSV template
          </a>
        }
      />

      {/* 5-Stage Scientific Gate Stepper */}
      <div className="calibration-stepper panel">
        <div className="stepper-track">
          {CALIBRATION_STEPS.map((step, idx) => {
            const isComplete = idx < currentStepIndex || (isReady && idx === 4);
            const isCurrent = idx === currentStepIndex && !isReady;
            return (
              <div
                key={step.id}
                className={`stepper-step ${isComplete ? "complete" : ""} ${isCurrent ? "current" : ""}`}
              >
                <div className="step-badge">
                  {isComplete ? <CheckCircle2 size={14} /> : <span>{idx + 1}</span>}
                </div>
                <div className="step-content">
                  <span className="step-kicker">{step.label}</span>
                  <strong>{step.title}</strong>
                  <small>{step.desc}</small>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {actionMessage && (
        <div className="response-context-banner">
          <Sparkles size={18} />
          <div>
            <strong>Operational status update</strong>
            <p>{actionMessage}</p>
          </div>
        </div>
      )}

      {loading && !data ? (
        <LoadingState label="Checking calibration registry" />
      ) : error ? (
        <EmptyState
          error
          title={error.code}
          body={error.message}
          action={<button onClick={() => void reload()}>Try again</button>}
        />
      ) : (
        data && (
          <>
            {/* Dual-State Hero: CALIBRATION_REQUIRED vs READY */}
            {isReady ? (
              <section className="calibration-hero panel ready">
                <div className="calibration-lock unlocked">
                  <Unlock size={34} />
                </div>
                <div className="calibration-copy">
                  <StatusBadge status="READY" />
                  <h2>Active Model: {data.active_model?.version || "Calibrated"}</h2>
                  <p>
                    Biomass density (kg DM/ha) and dynamic Grazing Capacity Horizon are formally
                    unlocked for the {pilot.name} operating area.
                  </p>
                  {data.active_model && (
                    <div className="active-formula-chip">
                      <code>
                        DM (kg/ha) = {data.active_model.coefficients?.slope?.toFixed(1) ?? "—"} × NDVI +{" "}
                        {data.active_model.coefficients?.intercept?.toFixed(1) ?? "—"}
                      </code>
                    </div>
                  )}
                </div>
                <div className="sample-counter">
                  <span>Model Quality (R²)</span>
                  <strong>{data.active_model?.metrics.r2.toFixed(3) ?? "—"}</strong>
                  <small>
                    RMSE: {data.active_model?.metrics.rmse.toFixed(1) ?? "—"} kg/ha (
                    {data.active_model?.metrics.n_samples ?? 0} samples)
                  </small>
                </div>
              </section>
            ) : (
              <section className="calibration-hero panel">
                <div className="calibration-lock">
                  <LockKeyhole size={34} />
                </div>
                <div className="calibration-copy">
                  <StatusBadge status={data.status} />
                  <h2>No biomass estimate is being displayed</h2>
                  <p>
                    {data.message} This prevents a vegetation index from being misrepresented as
                    kilograms of dry matter.
                  </p>
                </div>
                <div className="sample-counter">
                  <span>Validated samples</span>
                  <strong>{data.sample_count}</strong>
                  <small>{matchedCount} scene-matched</small>
                </div>
              </section>
            )}

            {/* Scientific Calibration Models & Fitting Section */}
            <section className="panel models-panel">
              <div className="models-panel-header">
                <div>
                  <span className="panel-kicker">EMPIRICAL REGRESSION COHORTS</span>
                  <h2>Calibration Model Registry</h2>
                </div>
                <button
                  className="button primary"
                  disabled={matchedCount < 3}
                  onClick={() => setIsFittingOpen((prev) => !prev)}
                >
                  <Beaker size={16} /> Fit Candidate Model
                </button>
              </div>

              {matchedCount < 3 && (
                <p className="data-note">
                  Least-squares regression requires at least 3 scene-matched field samples within ±5
                  days of cloud-filtered Sentinel-2 acquisitions. Currently matched:{" "}
                  <strong>{matchedCount}</strong>.
                </p>
              )}

              {isFittingOpen && (
                <div className="fit-model-box">
                  <div className="panel-header compact">
                    <div>
                      <span className="panel-kicker">REGRESSION RUNTIME</span>
                      <h3>Fit Ordinary Least Squares Model</h3>
                    </div>
                  </div>
                  {fitError && <p className="error-text">{fitError}</p>}
                  <div className="fit-form-grid">
                    <label>
                      <span>Algorithm</span>
                      <select
                        value={fitAlgorithm}
                        onChange={(e) => setFitAlgorithm(e.target.value)}
                      >
                        <option value="linear_ols">Linear OLS (NDVI → DM kg/ha)</option>
                      </select>
                    </label>
                    <label>
                      <span>Operational Notes</span>
                      <input
                        placeholder="e.g. Wet season calibration cohort"
                        value={fitNotes}
                        onChange={(e) => setFitNotes(e.target.value)}
                      />
                    </label>
                    <div className="capture-actions">
                      <button
                        className="button primary"
                        disabled={fitting}
                        onClick={() => void handleFitModel()}
                      >
                        {fitting ? "Fitting..." : "Run Regression"}
                      </button>
                      <button
                        className="button secondary"
                        onClick={() => setIsFittingOpen(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className="models-list">
                {models.data?.models.length === 0 ? (
                  <p className="data-note">
                    No models fitted yet. Once at least 3 field samples are matched to Sentinel-2
                    acquisitions, fit an empirical regression candidate.
                  </p>
                ) : (
                  models.data?.models.map((model) => {
                    const slope = model.coefficients?.slope as number | undefined;
                    const intercept = model.coefficients?.intercept as number | undefined;
                    const isCandidate = model.status === "candidate";
                    const isActive = model.status === "active";

                    return (
                      <article
                        key={model.id}
                        className={`model-card ${isActive ? "active" : ""}`}
                      >
                        <div>
                          <StatusBadge status={model.status} />
                        </div>
                        <div>
                          <div className="model-card-header">
                            <h3>{model.version}</h3>
                            <small>{new Date(model.created_at).toLocaleDateString()}</small>
                          </div>
                          <div className="model-card-metrics">
                            <span>Algorithm: <strong>{model.algorithm}</strong></span>
                            {slope != null && intercept != null && (
                              <span>
                                Formula: <strong>DM = {slope.toFixed(1)}×NDVI + {intercept.toFixed(1)}</strong>
                              </span>
                            )}
                            <span>R²: <strong>{model.metrics.r2.toFixed(3)}</strong></span>
                            <span>RMSE: <strong>{model.metrics.rmse.toFixed(1)} kg/ha</strong></span>
                            <span>MAE: <strong>{model.metrics.mae.toFixed(1)} kg/ha</strong></span>
                            <span>N: <strong>{model.metrics.n_samples} samples</strong></span>
                          </div>
                          {model.notes && <p className="data-note">{model.notes}</p>}
                        </div>
                        <div className="model-card-actions">
                          {isCandidate && (
                            auth.isOwner ? (
                              <button
                                className="button primary"
                                disabled={activatingId === model.id}
                                onClick={() => void handleActivateModel(model.id)}
                              >
                                <Sparkles size={14} /> {activatingId === model.id ? "Activating..." : "Activate Model"}
                              </button>
                            ) : (
                              <span className="coverage-warning">Owner required to activate</span>
                            )
                          )}
                          {isActive && (
                            <span className="response-mission-tag">Active Surface</span>
                          )}
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </section>

            {/* Interactive Grazing Capacity Horizon (GCH) Calculator */}
            {isReady ? (
              <section className="panel gch-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-kicker">DYNAMIC SUSTAINABILITY SIMULATOR</span>
                    <h2>Grazing Capacity Horizon (GCH)</h2>
                  </div>
                  <Calculator size={20} />
                </div>

                <div className="gch-calc-grid">
                  <div className="gch-form">
                    <label>
                      <span>Herd Size (TLU)</span>
                      <input
                        type="number"
                        min="1"
                        max="5000"
                        value={herdTlu}
                        onChange={(e) => setHerdTlu(Math.max(1, Number(e.target.value)))}
                      />
                      <small>1 Tropical Livestock Unit (TLU) = 250 kg = 6.25 kg DM/day intake.</small>
                    </label>

                    <label>
                      <span>
                        Forage Utilization Factor: <strong>{(utilizationFactor * 100).toFixed(0)}%</strong>
                      </span>
                      <input
                        type="range"
                        min="0.10"
                        max="0.70"
                        step="0.05"
                        value={utilizationFactor}
                        onChange={(e) => setUtilizationFactor(Number(e.target.value))}
                      />
                      <small>Recommended 30%–50% to preserve vegetative cover and root reserves.</small>
                    </label>

                    <button
                      className="button primary"
                      disabled={calculatingGch}
                      onClick={() => void handleCalculateGch()}
                    >
                      <Calculator size={16} /> {calculatingGch ? "Evaluating hexes..." : "Calculate Grazing Horizon"}
                    </button>
                    {gchError && <p className="error-text">{gchError}</p>}
                  </div>

                  <div className="gch-results-wrap">
                    {gchResult ? (
                      <>
                        <div
                          className={`gch-hero-card ${
                            gchResult.grazing_horizon_days > 30
                              ? "sustainable"
                              : gchResult.grazing_horizon_days >= 14
                              ? "moderate"
                              : "critical"
                          }`}
                        >
                          <span className="panel-kicker">CALCULATED SUSTAINABLE GRAZING HORIZON</span>
                          <div className="gch-days-number">
                            {Math.round(gchResult.grazing_horizon_days)} DAYS
                          </div>
                          <p>
                            {gchResult.grazing_horizon_days > 30
                              ? "Sustainable carrying capacity for current stocking rate."
                              : gchResult.grazing_horizon_days >= 14
                              ? "Moderate forage buffer. Monitor pasture depletion."
                              : "Critical forage deficit warning. Immediate herd rotation recommended."}
                          </p>
                        </div>

                        <div className="gch-metrics-grid">
                          <div className="gch-metric-box">
                            <span>Usable Forage</span>
                            <strong>
                              {Math.round(gchResult.usable_forage_kg_dm).toLocaleString()} kg DM
                            </strong>
                          </div>
                          <div className="gch-metric-box">
                            <span>Total Biomass</span>
                            <strong>
                              {Math.round(gchResult.total_biomass_kg_dm).toLocaleString()} kg DM
                            </strong>
                          </div>
                          <div className="gch-metric-box">
                            <span>Daily Demand</span>
                            <strong>
                              {Math.round(gchResult.daily_consumption_kg_dm).toLocaleString()} kg/day
                            </strong>
                          </div>
                          <div className="gch-metric-box">
                            <span>Mean Density</span>
                            <strong>
                              {Math.round(gchResult.mean_biomass_kg_ha).toLocaleString()} kg/ha
                            </strong>
                          </div>
                        </div>
                      </>
                    ) : (
                      <EmptyState
                        title="Configure herd parameters"
                        body="Set stocking rate and utilization factor to compute sustainable grazing horizon across all pilot cells."
                      />
                    )}
                  </div>
                </div>
              </section>
            ) : (
              <section className="panel capacity-formula">
                <span className="panel-kicker">FUTURE GCH EQUATION</span>
                <h2>Usable forage ÷ daily herd demand</h2>
                <div className="formula">
                  <span>calibrated kg DM/ha × actual cell area × required utilization factor</span>
                  <hr />
                  <span>TLU count × 6.25 kg DM/day</span>
                </div>
                <p>
                  No utilization factor receives a hidden default. It must be supplied and documented
                  for the operating context.
                </p>
              </section>
            )}

            <div className="capacity-grid">
              <section className="panel readiness-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-kicker">CALIBRATION CONTRACT</span>
                    <h2>Required field evidence</h2>
                  </div>
                  <FlaskConical size={20} />
                </div>
                <div className="contract-list">
                  {data.required_fields.map((field, index) => (
                    <div key={field}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <code>{field}</code>
                      <small>Required</small>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel methodology-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-kicker">ACTIVATION GATE</span>
                    <h2>From sample to decision</h2>
                  </div>
                  <Beaker size={20} />
                </div>
                <ol className="method-steps">
                  <li>
                    <span><Sprout size={18} /></span>
                    <div>
                      <strong>Collect dry matter</strong>
                      <p>Georeferenced, dated quadrat measurements with documented method.</p>
                    </div>
                  </li>
                  <li>
                    <span><Scale size={18} /></span>
                    <div>
                      <strong>Match Earth observation</strong>
                      <p>Pair field samples to cloud-free Sentinel-2 acquisitions within ±5 days.</p>
                    </div>
                  </li>
                  <li>
                    <span><CheckCircle2 size={18} /></span>
                    <div>
                      <strong>Validate before activation</strong>
                      <p>Publish R², RMSE, and MAE error metrics before activating a model version.</p>
                    </div>
                  </li>
                </ol>
              </section>

              <section className="panel sample-capture-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-kicker">FIELD QUEUE</span>
                    <h2>Capture a real sample</h2>
                  </div>
                  <ClipboardPlus size={20} />
                </div>
                <p className="data-note">
                  Stored only on this device until you export and submit the protected CSV import.
                </p>
                <div className="sample-form">
                  <label>
                    <span>Sample ID</span>
                    <input
                      value={draft.sample_id}
                      onChange={(event) => setDraft({ ...draft, sample_id: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>Sampled at</span>
                    <input
                      type="datetime-local"
                      value={draft.sampled_at}
                      onChange={(event) => setDraft({ ...draft, sampled_at: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>Latitude</span>
                    <input
                      type="number"
                      step="any"
                      value={draft.latitude}
                      onChange={(event) => setDraft({ ...draft, latitude: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>Longitude</span>
                    <input
                      type="number"
                      step="any"
                      value={draft.longitude}
                      onChange={(event) => setDraft({ ...draft, longitude: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>Dry matter kg/ha</span>
                    <input
                      type="number"
                      min="0"
                      value={draft.dry_matter_kg_ha}
                      onChange={(event) =>
                        setDraft({ ...draft, dry_matter_kg_ha: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    <span>Quadrat area m²</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.quadrat_area_m2}
                      onChange={(event) =>
                        setDraft({ ...draft, quadrat_area_m2: event.target.value })
                      }
                    />
                  </label>
                  <label className="wide">
                    <span>Method</span>
                    <input
                      value={draft.method}
                      onChange={(event) => setDraft({ ...draft, method: event.target.value })}
                    />
                  </label>
                </div>
                <div className="capture-actions">
                  <button className="button secondary" onClick={locate}>
                    <LocateFixed size={16} /> Use GPS
                  </button>
                  <button className="button primary" onClick={saveDraft}>
                    Queue sample
                  </button>
                  <button
                    className="button secondary"
                    disabled={!drafts.length}
                    onClick={exportDrafts}
                  >
                    <Download size={16} /> Export {drafts.length}
                  </button>
                </div>
              </section>

              <section className="panel sample-coverage-panel">
                <div className="panel-header">
                  <div>
                    <span className="panel-kicker">REGISTERED EVIDENCE</span>
                    <h2>Sample coverage</h2>
                  </div>
                  <StatusBadge
                    status={coverage.data?.meta.sample_count ? "collecting" : "awaiting samples"}
                  />
                </div>
                <div className="coverage-stats">
                  <div>
                    <span>Imported</span>
                    <strong>{coverage.data?.meta.sample_count || 0}</strong>
                  </div>
                  <div>
                    <span>Scene matched</span>
                    <strong>{coverage.data?.meta.scene_matched_count || 0}</strong>
                  </div>
                  <div>
                    <span>Pending match</span>
                    <strong>{coverage.data?.meta.unmatched_count || 0}</strong>
                  </div>
                </div>
                <div className="sample-map">
                  <ScienceMap pilot={pilot} samples={coverage.data || null} />
                </div>
              </section>
            </div>
            <EvidenceNote>
              Imported samples can document spatial and scene coverage, but only a separately
              validated and activated model can unlock biomass and GCH calculations.
            </EvidenceNote>
          </>
        )
      )}
    </div>
  );
}
