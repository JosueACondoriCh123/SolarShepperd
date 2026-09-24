import { Cloud, Layers3, Map as MapIcon, Satellite, ScanSearch } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiGet } from "../api";
import { EmptyState, LoadingState, StatusBadge } from "../components/DataState";
import { EvidenceNote } from "../components/EvidenceNote";
import { PageHeader } from "../components/PageHeader";
import { MapLegend } from "../components/MapLegend";
import { ScienceMap } from "../components/ScienceMap";
import { useApi } from "../hooks/useApi";
import { usePilot } from "../pilot/PilotContext";
import type {
  CellCollection, CellFeature, PilotMapContext, SceneResponse, SceneTiles,
} from "../types";

const layerOptions = [
  { value: "ndvi", label: "NDVI", detail: "Vegetation vigor" },
  { value: "ndmi", label: "NDMI", detail: "Canopy moisture" },
  { value: "biomass", label: "Biomass", detail: "Calibrated kg DM/ha" },
  { value: "delta_ndvi", label: "ΔNDVI", detail: "Change between scenes" },
  { value: "delta_ndmi", label: "ΔNDMI", detail: "Moisture change" },
  { value: "forage_proxy", label: "Forage proxy", detail: "Relative, not biomass" },
  { value: "elevation", label: "Elevation", detail: "Copernicus GLO-30" },
  { value: "slope", label: "Slope", detail: "Terrain constraint" },
  { value: "water", label: "Water", detail: "OSM coverage" },
] as const;

export function LandscapePage() {
  const { pilot } = usePilot();
  const [layer, setLayer] = useState<string>("ndvi");
  const [baseLayer, setBaseLayer] = useState<"osm" | "sentinel">("osm");
  const [fromScene, setFromScene] = useState("");
  const [toScene, setToScene] = useState("");
  const [selected, setSelected] = useState<CellFeature | null>(null);
  const bbox = pilot.bbox.join(",");
  const context = useApi<PilotMapContext>(
    () => apiGet(`/pilots/${pilot.slug}/context`),
    [pilot.slug],
    120_000,
  );
  const scenes = useApi<SceneResponse>(() => apiGet("/scenes?limit=20"), [pilot.slug], 120_000);

  useEffect(() => {
    const available = scenes.data?.data || [];
    if (!available.length) return;
    if (!available.some((scene) => scene.id === toScene)) setToScene(available[0].id);
    if (available.length > 1 && !available.some((scene) => scene.id === fromScene)) {
      setFromScene(available[1].id);
    }
  }, [fromScene, scenes.data, toScene]);

  const isChange = layer.startsWith("delta_");
  const isWater = layer === "water";
  const comparisonReady = (scenes.data?.data.length || 0) >= 2;
  const selectedScene = scenes.data?.data.find((scene) => scene.id === toScene);
  const path = useMemo(() => {
    if (isWater) return null;
    if (isChange && fromScene && toScene) {
      return `/cells/change?bbox=${encodeURIComponent(bbox)}&from_scene_id=${encodeURIComponent(fromScene)}&to_scene_id=${encodeURIComponent(toScene)}&layer=${layer.replace("delta_", "")}`;
    }
    const date = selectedScene?.acquired_at.slice(0, 10);
    return `/cells?bbox=${encodeURIComponent(bbox)}&layer=${layer}${date ? `&date=${date}` : ""}`;
  }, [bbox, fromScene, isChange, isWater, layer, selectedScene?.acquired_at, toScene]);
  const cells = useApi<CellCollection>(() => apiGet(path!), [path, pilot.slug], undefined, Boolean(path));
  const tiles = useApi<SceneTiles>(
    () => apiGet(`/pilots/${pilot.slug}/scenes/${toScene}/tiles`),
    [pilot.slug, toScene],
    undefined,
    Boolean(toScene),
  );
  const latestScene = scenes.data?.data[0];
  const selectedLayer = layerOptions.find((item) => item.value === layer);
  const requiresScene = ["ndvi", "ndmi", "biomass", "forage_proxy"].includes(layer) || isChange;
  const coverageInsufficient = Boolean(
    cells.data?.features.length
    && cells.data.features.every((feature) => feature.properties.value == null)
    && cells.data.features.some((feature) => feature.properties.quality_flags.includes("LOW_VALID_PIXEL_COVERAGE")),
  );

  useEffect(() => setSelected(null), [layer, fromScene, pilot.slug, toScene]);

  return (
    <div className="page map-page">
      <PageHeader
        kicker={`02 / ${pilot.name} Earth observation`}
        title="Landscape explorer"
        description={`Observed landscape evidence within the ${pilot.radius_km} km ${pilot.name} pilot boundary.`}
        actions={
          <div className="scene-controls">
            {isChange && (
              <label className="select-control"><span>From</span><select value={fromScene} onChange={(event) => setFromScene(event.target.value)}>{[...(scenes.data?.data || [])].reverse().map((scene) => <option key={scene.id} value={scene.id}>{new Date(scene.acquired_at).toLocaleDateString()}</option>)}</select></label>
            )}
            <label className="select-control"><span>{isChange ? "To" : "Scene"}</span><select aria-label="Sentinel scene" value={toScene} onChange={(event) => setToScene(event.target.value)}>{(scenes.data?.data || []).map((scene) => <option key={scene.id} value={scene.id}>{new Date(scene.acquired_at).toLocaleDateString()}</option>)}</select></label>
          </div>
        }
      />

      <div className="map-layout">
        <aside className="layer-rail panel">
          <div className="panel-header compact"><div><span className="panel-kicker">BASE MAP</span><h2>Evidence stack</h2></div><Layers3 size={18} /></div>
          <div className="basemap-switch" role="group" aria-label="Base map">
            <button className={baseLayer === "osm" ? "active" : ""} onClick={() => setBaseLayer("osm")}><MapIcon size={14} /> OSM</button>
            <button disabled={!tiles.data} className={baseLayer === "sentinel" ? "active" : ""} onClick={() => setBaseLayer("sentinel")}><Satellite size={14} /> Sentinel true-color</button>
          </div>
          <div className="layer-list">
            {layerOptions.map((option) => (
              <button key={option.value} disabled={option.value.startsWith("delta_") && !comparisonReady} className={layer === option.value ? "active" : ""} onClick={() => setLayer(option.value)}>
                <span className="layer-radio" /><span><strong>{option.label}</strong><small>{option.detail}</small></span>
              </button>
            ))}
          </div>
          <div className="scene-summary"><Satellite size={18} /><div><span>Latest scene</span><strong>{latestScene ? new Date(latestScene.acquired_at).toLocaleDateString() : "Not ingested"}</strong></div></div>
          {latestScene && <div className="scene-stats"><div><Cloud size={15} /><span>Cloud</span><strong>{latestScene.cloud_cover_pct?.toFixed(1) ?? "—"}%</strong></div><div><ScanSearch size={15} /><span>Valid</span><strong>{latestScene.valid_fraction == null ? "—" : `${(latestScene.valid_fraction * 100).toFixed(0)}%`}</strong></div></div>}
          {!isWater && <MapLegend layer={layer} />}
          <div className="map-provenance"><strong>{selectedLayer?.label}</strong><span>{isWater ? "OpenStreetMap / Overpass" : selectedScene?.source || "No source yet"}</span><span>{selectedScene ? new Date(selectedScene.acquired_at).toLocaleString() : "No acquisition"}</span></div>
        </aside>

        <section className="map-stage panel">
          <ScienceMap pilot={pilot} context={context.data} cells={isWater ? null : cells.data} layer={layer} baseLayer={baseLayer} sceneTiles={tiles.data} onCellSelect={setSelected} />
          <div className="map-stage-label"><span className="signal-dot" /> {isWater ? "OSM water evidence" : isChange ? "Scene comparison" : "Analytical surface"}</div>
          {(cells.loading || context.loading) && <div className="map-overlay-state"><LoadingState label="Reading spatial evidence" /></div>}
          {(cells.error || context.error) && <div className="map-overlay-state"><EmptyState error title={(cells.error || context.error)!.code} body={(cells.error || context.error)!.message} /></div>}
          {requiresScene && !scenes.loading && !scenes.data?.data.length && <div className="map-overlay-state"><EmptyState title="No Sentinel scene" body="No complete cloud-filtered acquisition covers this pilot yet." /></div>}
          {coverageInsufficient && <div className="map-overlay-state"><EmptyState title="Insufficient coverage" body="The available cells are transparent because valid pixel coverage is below the scientific threshold." /></div>}
          {!requiresScene && !isWater && !cells.loading && !cells.error && cells.data?.features.length === 0 && <div className="map-overlay-state"><EmptyState title="No cells for this layer yet" body="The source has no complete surface for this pilot; no color has been inferred." /></div>}
          {baseLayer === "sentinel" && tiles.error && <div className="map-overlay-state"><EmptyState error title="SENTINEL_TILES_UNAVAILABLE" body={tiles.error.message} /></div>}
        </section>

        <aside className="cell-inspector panel">
          {selected ? (
            <>
              <div className="panel-header compact"><div><span className="panel-kicker">SELECTED HEX</span><h2>{selected.properties.h3_index}</h2></div><StatusBadge status={selected.properties.value == null ? "no data" : "observed"} /></div>
              <div className="inspection-value"><span>{selectedLayer?.label}</span><strong>{selected.properties.value == null ? "—" : selected.properties.value.toFixed(3)}</strong><small>{selected.properties.unit}</small></div>
              {isChange && <div className="change-values"><div><span>Earlier</span><strong>{selected.properties.from_value?.toFixed(3) ?? "—"}</strong></div><div><span>Later</span><strong>{selected.properties.to_value?.toFixed(3) ?? "—"}</strong></div></div>}
              <dl className="inspection-list"><div><dt>Cell area</dt><dd>{selected.properties.area_ha.toFixed(1)} ha</dd></div><div><dt>Valid pixels</dt><dd>{selected.properties.valid_fraction == null ? "—" : `${(selected.properties.valid_fraction * 100).toFixed(0)}%`}</dd></div><div><dt>Acquired</dt><dd>{selected.properties.observed_at ? new Date(selected.properties.observed_at).toLocaleDateString() : "—"}</dd></div><div><dt>Source</dt><dd>{selected.properties.source || "—"}</dd></div><div><dt>Model</dt><dd>{selected.properties.model_version || "not applicable"}</dd></div></dl>
              {selected.properties.quality_flags.length > 0 && <div className="quality-list"><strong>Quality</strong>{selected.properties.quality_flags.map((flag) => <span key={flag}>{flag}</span>)}</div>}
              {selected.properties.biomass_calibrated ? (
                <div className="calibration-notice success">
                  <strong>Biomass Calibrated</strong>
                  <p>Model {selected.properties.model_version || "Active"}: {selected.properties.value == null ? "—" : selected.properties.value.toFixed(1)} kg DM/ha</p>
                </div>
              ) : (
                <div className="calibration-warning"><strong>Biomass locked</strong><p>Index values and changes are not kilograms of dry matter.</p></div>
              )}
            </>
          ) : (
            <div className="zone-evidence">
              <span className="panel-kicker">ZONE EVIDENCE</span><h2>{pilot.name}</h2>
              <StatusBadge status={pilot.observation_status} />
              <dl className="inspection-list"><div><dt>Boundary</dt><dd>{pilot.radius_km} km radius</dd></div><div><dt>Stations</dt><dd>{context.data?.stations.features.length ?? "—"}</dd></div><div><dt>Water features</dt><dd>{context.data?.water.features.length ?? "—"}</dd></div><div><dt>Timezone</dt><dd>{pilot.timezone}</dd></div></dl>
              {context.data?.stations.features.map((station) => <article className="station-evidence" key={station.properties.station_id}><strong>{station.properties.name}</strong><span>{station.properties.source} · {(station.properties.distance_to_center_m / 1_000).toFixed(1)} km away</span>{station.properties.outside_pilot && <StatusBadge status="outside pilot" />}</article>)}
              <p className="coverage-warning">{context.data?.water_coverage_warning}</p>
              <EmptyState title="Inspect a hexagon" body="Select a cell to review value, quality and provenance." />
            </div>
          )}
        </aside>
      </div>
      <EvidenceNote>Transparent cells have no usable observation. Change layers subtract two cloud-masked acquisitions and do not claim biomass gain or loss.</EvidenceNote>
    </div>
  );
}
