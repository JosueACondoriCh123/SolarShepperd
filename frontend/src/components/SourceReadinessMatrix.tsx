import type { OperationsStatus } from "../types";
import { EmptyState, StatusBadge } from "./DataState";

function formatSourceAge(seconds: number | null) {
  if (seconds == null) return "never";
  if (seconds < 3_600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `${(seconds / 3_600).toFixed(1)} h`;
  return `${(seconds / 86_400).toFixed(1)} d`;
}

export function SourceReadinessMatrix({ sources }: { sources: OperationsStatus["sources"] }) {
  if (!sources.length) return <EmptyState title="No matching sources" body="Change the source filter or wait for the registry to refresh." />;
  return (
    <div className="readiness-grid">
      {sources.map((source) => (
        <article key={source.source}>
          <div><strong>{source.source}</strong><StatusBadge status={source.status} /></div>
          <span>Latest run · {source.latest_run_at ? new Date(source.latest_run_at).toLocaleString() : "never"}</span>
          <span>Last success · {source.last_success_at ? new Date(source.last_success_at).toLocaleString() : "never"}</span>
          <span>Age · {formatSourceAge(source.age_seconds)}</span>
          <span>Next run · {source.next_scheduled_at ? new Date(source.next_scheduled_at).toLocaleString() : "manual"}</span>
          {source.error_code && <code>{source.error_code}</code>}
        </article>
      ))}
    </div>
  );
}
