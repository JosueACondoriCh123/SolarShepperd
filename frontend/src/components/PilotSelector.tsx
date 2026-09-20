import type { Pilot } from "../types";
import { StatusBadge } from "./DataState";

export function PilotSelector({
  pilot,
  pilots,
  onSelect,
}: {
  pilot: Pilot;
  pilots: Pilot[];
  onSelect: (slug: string) => void;
}) {
  return (
    <label className="pilot-selector">
      <span><span className="signal-dot" /> Active pilot</span>
      <select aria-label="Active pilot" value={pilot.slug} onChange={(event) => onSelect(event.target.value)}>
        {pilots.map((item) => (
          <option key={item.slug} value={item.slug}>{item.name} · {item.radius_km} km</option>
        ))}
      </select>
      <StatusBadge status={pilot.observation_status} />
    </label>
  );
}
