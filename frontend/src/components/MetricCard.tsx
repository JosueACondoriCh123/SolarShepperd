import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: number | null;
  unit?: string;
  icon: LucideIcon;
  observedAt?: string | null;
  source?: string;
  accent?: "green" | "amber" | "blue" | "violet";
  previous?: number | null;
  qualityFlags?: string[];
  modelVersion?: string | null;
}

export function MetricCard({
  label,
  value,
  unit,
  icon: Icon,
  observedAt,
  source,
  accent = "green",
  previous,
  qualityFlags = [],
  modelVersion,
}: MetricCardProps) {
  const delta = value != null && previous != null ? value - previous : null;
  const Trend = delta == null || Math.abs(delta) < 0.001 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <article className={`metric-card ${accent}`}>
      <div className="metric-topline">
        <span>{label}</span>
        <div className="metric-icon"><Icon size={19} /></div>
      </div>
      <div className="metric-value">
        {value == null ? <span className="unavailable">—</span> : value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        {value != null && unit && <small>{unit}</small>}
      </div>
      <div className="metric-meta">
        <span className="trend"><Trend size={14} />{delta == null ? "No comparison" : `${Math.abs(delta).toFixed(1)} latest change`}</span>
        <span>{observedAt ? new Date(observedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Awaiting data"}</span>
      </div>
      {(source || modelVersion || qualityFlags.length > 0) && (
        <div className="metric-source">
          {source && <span>SOURCE · {source}</span>}
          {modelVersion && <span>MODEL · {modelVersion}</span>}
          {qualityFlags.length > 0 && <span>QUALITY · {qualityFlags.join(" · ")}</span>}
        </div>
      )}
    </article>
  );
}
