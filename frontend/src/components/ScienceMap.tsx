import { MapboxOverlay } from "@deck.gl/mapbox";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { GeoJsonLayer } from "@deck.gl/layers";
import maplibregl, { type IControl, type Map as MapLibreMap } from "maplibre-gl";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import type { CellCollection, CellFeature, Pilot, PilotMapContext, SceneTiles } from "../types";

interface ScienceMapProps {
  pilot: Pilot;
  context?: PilotMapContext | null;
  cells?: CellCollection | null;
  layer?: string;
  baseLayer?: "osm" | "sentinel";
  sceneTiles?: SceneTiles | null;
  route?: GeoJSON.FeatureCollection | null;
  onCellSelect?: (feature: CellFeature) => void;
  onCoordinateClick?: (longitude: number, latitude: number) => void;
  start?: [number, number] | null;
  end?: [number, number] | null;
  samples?: GeoJSON.FeatureCollection | null;
}

function colorForValue(value: number | null, layer: string): [number, number, number, number] {
  if (value == null) return [0, 0, 0, 0];
  if (layer.startsWith("delta_")) {
    const magnitude = Math.min(1, Math.abs(value) / 0.3);
    return value < 0
      ? [220, Math.round(190 - 115 * magnitude), 64, 205]
      : [Math.round(226 - 150 * magnitude), Math.round(190 + 35 * magnitude), 92, 205];
  }
  if (layer === "biomass") {
    const t = Math.max(0, Math.min(1, value / 2500));
    return [Math.round(212 * (1 - t) + 45 * t), Math.round(176 * (1 - t) + 122 * t), Math.round(94 * (1 - t) + 70 * t), 195];
  }
  if (layer === "slope") {
    const t = Math.max(0, Math.min(1, value / 25));
    return [Math.round(235 * t + 45), Math.round(175 * (1 - t) + 70), 67, 185];
  }
  if (layer === "elevation") {
    const t = Math.max(0, Math.min(1, (value - 1300) / 600));
    return [Math.round(45 + 80 * t), Math.round(120 + 80 * (1 - t)), Math.round(180 - 60 * t), 185];
  }
  const t = Math.max(0, Math.min(1, layer === "forage_proxy" ? value : (value + 1) / 2));
  return [Math.round(178 - 130 * t), Math.round(85 + 145 * t), Math.round(65 + 50 * (1 - t)), 190];
}

function MapSkeleton() {
  return (
    <div className="map-skeleton" aria-hidden="true">
      <div className="map-skeleton-grid" />
      <div className="map-skeleton-radar">
        <div className="signal-dot green" />
      </div>
      <div className="map-skeleton-text">
        <span>INITIALIZING GEOSPATIAL RUNTIME · H3-R9</span>
      </div>
    </div>
  );
}

export const ScienceMap = memo(function ScienceMap({
  pilot,
  context,
  cells,
  layer = "ndvi",
  baseLayer = "osm",
  sceneTiles,
  route,
  onCellSelect,
  onCoordinateClick,
  start,
  end,
  samples,
}: ScienceMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const activeSceneRef = useRef<string | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  const clickCallback = useRef(onCoordinateClick);
  clickCallback.current = onCoordinateClick;

  const selectCallback = useRef(onCellSelect);
  selectCallback.current = onCellSelect;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    let cancelled = false;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [pilot.center.longitude, pilot.center.latitude],
      zoom: 11.7,
      pitch: 42,
      bearing: -12,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
            paint: {
              "raster-saturation": -0.68,
              "raster-contrast": 0.12,
              "raster-brightness-min": 0.18,
              "raster-brightness-max": 0.92,
            },
          },
        ],
      },
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }));

    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(overlay as unknown as IControl);

    map.on("load", () => {
      if (!cancelled) setMapLoaded(true);
    });

    map.on("click", (event) => clickCallback.current?.(event.lngLat.lng, event.lngLat.lat));

    mapRef.current = map;
    overlayRef.current = overlay;

    return () => {
      cancelled = true;
      try {
        overlay.finalize();
      } catch {
        // Overlay cleanup safety
      }
      try {
        map.remove();
      } catch {
        // Map cleanup safety
      }
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, [pilot.center.latitude, pilot.center.longitude]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    map.fitBounds(
      [[pilot.bbox[0], pilot.bbox[1]], [pilot.bbox[2], pilot.bbox[3]]],
      { padding: 34, duration: 0 },
    );
  }, [mapLoaded, pilot.bbox]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const hasSentinel = Boolean(sceneTiles?.tilejson_url);
    if (activeSceneRef.current !== (sceneTiles?.scene_id || null)) {
      if (map.getLayer("sentinel-scene")) map.removeLayer("sentinel-scene");
      if (map.getSource("sentinel-scene")) map.removeSource("sentinel-scene");
      activeSceneRef.current = sceneTiles?.scene_id || null;
    }
    if (hasSentinel && !map.getSource("sentinel-scene")) {
      map.addSource("sentinel-scene", {
        type: "raster",
        url: sceneTiles!.tilejson_url,
        tileSize: 256,
        attribution: sceneTiles!.attribution,
      });
      map.addLayer({ id: "sentinel-scene", type: "raster", source: "sentinel-scene" });
    }
    if (map.getLayer("osm")) {
      map.setLayoutProperty("osm", "visibility", baseLayer === "sentinel" && hasSentinel ? "none" : "visible");
    }
    if (map.getLayer("sentinel-scene")) {
      map.setLayoutProperty("sentinel-scene", "visibility", baseLayer === "sentinel" && hasSentinel ? "visible" : "none");
    }
  }, [baseLayer, mapLoaded, sceneTiles]);

  const pointData = useMemo(
    () => [
      ...(start ? [{ kind: "start", coordinates: start }] : []),
      ...(end ? [{ kind: "end", coordinates: end }] : []),
    ],
    [start, end]
  );

  const memoizedLayers = useMemo(() => {
    const emptyCollection = { type: "FeatureCollection", features: [] } as GeoJSON.FeatureCollection;
    const stationConnectors: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: (context?.stations.features || []).map((station) => ({
        type: "Feature",
        properties: station.properties,
        geometry: {
          type: "LineString",
          coordinates: [
            [pilot.center.longitude, pilot.center.latitude],
            station.geometry.coordinates,
          ],
        },
      })),
    };
    const pilotCenter: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: { name: pilot.name },
        geometry: { type: "Point", coordinates: [pilot.center.longitude, pilot.center.latitude] },
      }],
    };
    return [
      new GeoJsonLayer({
        id: "pilot-boundary",
        data: context?.boundary || emptyCollection,
        filled: true,
        stroked: true,
        getFillColor: [255, 205, 70, 18],
        getLineColor: [23, 23, 23, 230],
        getLineWidth: 3,
        lineWidthMinPixels: 2,
      }),
      new GeoJsonLayer({
        id: "station-connectors",
        data: stationConnectors,
        getLineColor: [36, 101, 150, 175],
        getLineWidth: 2,
        lineWidthMinPixels: 1,
        getDashArray: [5, 4],
      }),
      new GeoJsonLayer({
        id: "pilot-water",
        data: context?.water || emptyCollection,
        pointType: "circle",
        getPointRadius: 55,
        pointRadiusMinPixels: 4,
        getFillColor: [36, 131, 190, 210],
        getLineColor: [21, 70, 105, 230],
        getLineWidth: 2,
        lineWidthMinPixels: 1,
        filled: true,
        stroked: true,
        pickable: true,
      }),
      new H3HexagonLayer<CellFeature>({
        id: "h3-science-layer",
        data: cells?.features || [],
        getHexagon: (feature) => feature.properties.h3_index,
        getFillColor: (feature) => colorForValue(feature.properties.value, layer),
        getLineColor: [28, 26, 22, 120],
        lineWidthMinPixels: 1,
        stroked: true,
        filled: true,
        extruded: layer === "elevation",
        getElevation: (feature) =>
          layer === "elevation" ? Math.max(0, (feature.properties.value || 0) - 1_300) * 1.5 : 0,
        elevationScale: 1,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 205, 70, 175],
        onClick: ({ object }) => object && selectCallback.current?.(object),
        updateTriggers: { getFillColor: [layer] },
      }),
      new GeoJsonLayer({
        id: "pilot-center",
        data: pilotCenter,
        pointType: "circle",
        getPointRadius: 65,
        pointRadiusMinPixels: 5,
        getFillColor: [255, 205, 70, 255],
        getLineColor: [23, 23, 23, 255],
        getLineWidth: 3,
        lineWidthMinPixels: 2,
        filled: true,
        stroked: true,
      }),
      new GeoJsonLayer({
        id: "observation-stations",
        data: context?.stations || emptyCollection,
        pointType: "circle",
        getPointRadius: 90,
        pointRadiusMinPixels: 7,
        getFillColor: [23, 107, 69, 255],
        getLineColor: [23, 23, 23, 255],
        getLineWidth: 3,
        lineWidthMinPixels: 2,
        filled: true,
        stroked: true,
        pickable: true,
      }),
      new GeoJsonLayer({
        id: "route-layer",
        data: route || { type: "FeatureCollection", features: [] },
        getLineColor: (feature: { properties?: { multiplier?: number } }) => {
          const multiplier = feature.properties?.multiplier;
          if (multiplier == null) return [23, 23, 23, 220];
          const risk = Math.max(0, Math.min(1, (multiplier - 0.6) / 1.0));
          return [Math.round(45 + 195 * risk), Math.round(190 - 120 * risk), 62, 245];
        },
        getLineWidth: (feature: { properties?: { multiplier?: number } }) =>
          feature.properties?.multiplier == null ? 7 : 4,
        lineWidthMinPixels: 3,
        pickable: true,
      }),
      new GeoJsonLayer({
        id: "route-endpoints",
        data: {
          type: "FeatureCollection",
          features: pointData.map((point) => ({
            type: "Feature",
            properties: { kind: point.kind },
            geometry: { type: "Point", coordinates: point.coordinates },
          })),
        },
        pointType: "circle",
        getPointRadius: 90,
        pointRadiusMinPixels: 7,
        getFillColor: (feature: { properties: { kind: string } }) =>
          feature.properties.kind === "start" ? [72, 230, 151, 255] : [255, 150, 78, 255],
        getLineColor: [23, 23, 23, 255],
        lineWidthMinPixels: 3,
        stroked: true,
        filled: true,
      }),
      new GeoJsonLayer({
        id: "calibration-samples",
        data: samples || { type: "FeatureCollection", features: [] },
        pointType: "circle",
        getPointRadius: 110,
        pointRadiusMinPixels: 7,
        getFillColor: [241, 167, 196, 245],
        getLineColor: [23, 23, 23, 255],
        lineWidthMinPixels: 3,
        stroked: true,
        filled: true,
        pickable: true,
      }),
    ];
  }, [cells?.features, context, layer, pilot, route, pointData, samples]);

  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.setProps({ layers: memoizedLayers });
  }, [memoizedLayers]);

  return (
    <div
      ref={containerRef}
      className="science-map"
      aria-label="Interactive geospatial map"
    >
      {!mapLoaded && <MapSkeleton />}
    </div>
  );
});
