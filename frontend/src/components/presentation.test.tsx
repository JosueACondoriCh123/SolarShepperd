import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { OperationsStatus, Pilot } from "../types";
import { EmptyState } from "./DataState";
import { MapLegend } from "./MapLegend";
import { PilotSelector } from "./PilotSelector";
import { SourceReadinessMatrix } from "./SourceReadinessMatrix";

const makePilot = (slug: string, name: string): Pilot => ({
  slug,
  name,
  center: { latitude: 0, longitude: 37 },
  radius_km: 10,
  timezone: "Africa/Nairobi",
  bbox: [36.9, -0.1, 37.1, 0.1],
  boundary: { type: "Polygon", coordinates: [] },
  observation_sources: ["NOAA Aviation Weather METAR"],
  latest_observed_at: null,
  observation_status: slug === "lodwar" ? "never_run" : "healthy",
});

const pilots = [makePilot("jkuat", "JKUAT"), makePilot("garissa", "Garissa"), makePilot("lodwar", "Lodwar")];

describe("pilot and map presentation", () => {
  it("offers all backend-provided pilots and emits the chosen slug", () => {
    const select = vi.fn();
    render(<PilotSelector pilot={pilots[0]} pilots={pilots} onSelect={select} />);
    expect(screen.getAllByRole("option")).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Active pilot"), { target: { value: "garissa" } });
    expect(select).toHaveBeenCalledWith("garissa");
  });

  it("uses a divergent legend for scene changes", () => {
    render(<MapLegend layer="delta_ndvi" />);
    expect(screen.getByLabelText("delta_ndvi legend").textContent).toContain("LOSS");
    expect(screen.getByLabelText("delta_ndvi legend").textContent).toContain("GAIN");
  });

  it("renders a recoverable empty state", () => {
    render(<EmptyState title="No cells" body="Run the source ingestion and retry." />);
    expect(screen.getByRole("heading", { name: "No cells" })).toBeTruthy();
    expect(screen.getByText(/retry/)).toBeTruthy();
  });
});

describe("operations readiness", () => {
  const sources: OperationsStatus["sources"] = [{
    pilot_slug: "garissa",
    source: "aviation_weather",
    status: "degraded",
    latest_run_status: "failed",
    latest_run_at: "2026-09-19T10:00:00Z",
    last_success_at: "2026-09-19T09:00:00Z",
    age_seconds: 7_200,
    error_code: "UPSTREAM_TIMEOUT",
    next_scheduled_at: "2026-09-19T12:00:00Z",
  }];

  it("shows source health, age and recoverable error code", () => {
    render(<SourceReadinessMatrix sources={sources} />);
    expect(screen.getByText("degraded")).toBeTruthy();
    expect(screen.getByText(/Age · 2.0 h/)).toBeTruthy();
    expect(screen.getByText("UPSTREAM_TIMEOUT")).toBeTruthy();
  });
});
