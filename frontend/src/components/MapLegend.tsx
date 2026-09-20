export function MapLegend({ layer }: { layer: string }) {
  const change = layer.startsWith("delta_");
  return (
    <div className="legend" aria-label={`${layer} legend`}>
      <span>{change ? "LOSS" : "LOW"}</span>
      <div className={`legend-ramp ${layer}`} />
      <span>{change ? "GAIN" : "HIGH"}</span>
    </div>
  );
}
