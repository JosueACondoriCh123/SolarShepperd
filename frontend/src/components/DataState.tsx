import { AlertTriangle, LoaderCircle, RadioTower } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  body: string;
  action?: ReactNode;
  error?: boolean;
}

export function EmptyState({ title, body, action, error = false }: EmptyStateProps) {
  const Icon = error ? AlertTriangle : RadioTower;
  return (
    <div className={`empty-state ${error ? "error" : ""}`}>
      <div className="empty-icon"><Icon size={24} /></div>
      <div>
        <h3>{title}</h3>
        <p>{body}</p>
        {action}
      </div>
    </div>
  );
}

export function LoadingState({ label = "Reading live sources" }: { label?: string }) {
  return (
    <div className="loading-state">
      <LoaderCircle size={18} className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized.includes("success") || normalized.includes("healthy") || normalized === "complete" || normalized === "ready"
    ? "success"
    : normalized.includes("fail") || normalized.includes("error") || normalized.includes("unavailable")
      ? "danger"
      : normalized.includes("required") || normalized.includes("mapping") || normalized.includes("stale") || normalized.includes("degraded") || normalized.includes("forecast")
        ? "warning"
        : "neutral";
  return <span className={`status-badge ${tone}`}>{status.replaceAll("_", " ")}</span>;
}
