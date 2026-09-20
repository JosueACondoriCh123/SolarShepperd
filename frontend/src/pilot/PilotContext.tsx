import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { apiGet, setActivePilotSlug } from "../api";
import { EmptyState, LoadingState } from "../components/DataState";
import type { Pilot, PilotsResponse } from "../types";

export const PILOT_STORAGE_KEY = "solarshepherd-active-pilot";

interface PilotValue {
  pilot: Pilot;
  pilots: Pilot[];
  selectPilot: (slug: string) => void;
}

const PilotContext = createContext<PilotValue | null>(null);

// eslint-disable-next-line react-refresh/only-export-components -- shared route helper
export function preferredPilotSlug() {
  return localStorage.getItem(PILOT_STORAGE_KEY) || "jkuat";
}

export function PilotProvider({ children }: PropsWithChildren) {
  const { pilotSlug = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [response, setResponse] = useState<PilotsResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let current = true;
    void apiGet<PilotsResponse>("/pilots")
      .then((value) => {
        if (current) setResponse(value);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason : new Error(String(reason)));
      });
    return () => {
      current = false;
    };
  }, []);

  const pilot = response?.data.find((item) => item.slug === pilotSlug);
  useEffect(() => {
    if (!response || pilot) return;
    const fallback = response.data.some((item) => item.slug === response.default_pilot_slug)
      ? response.default_pilot_slug
      : response.data[0]?.slug;
    if (!fallback) return;
    const suffix = location.pathname.replace(/^\/app\/[^/]+/, "");
    navigate(`/app/${fallback}${suffix || "/dashboard"}${location.search}`, {
      replace: true,
      state: { pilotNotice: `Pilot “${pilotSlug}” was not found. Showing ${fallback}.` },
    });
  }, [location.pathname, location.search, navigate, pilot, pilotSlug, response]);

  useEffect(() => {
    if (!pilot) return;
    const previous = localStorage.getItem(PILOT_STORAGE_KEY);
    localStorage.setItem(PILOT_STORAGE_KEY, pilot.slug);
    setActivePilotSlug(pilot.slug);
    if (previous !== pilot.slug) {
      window.dispatchEvent(new CustomEvent("solarshepherd-pilot-change", {
        detail: { previous, current: pilot.slug },
      }));
    }
    return () => setActivePilotSlug(null);
  }, [pilot]);

  const value = useMemo<PilotValue | null>(() => pilot && response ? {
    pilot,
    pilots: response.data,
    selectPilot: (slug) => {
      if (slug === pilot.slug) return;
      const nextPath = location.pathname.replace(`/app/${pilot.slug}`, `/app/${slug}`);
      navigate(`${nextPath}${location.search}`);
    },
  } : null, [location.pathname, location.search, navigate, pilot, response]);

  if (error) {
    return <div className="page-loading"><EmptyState error title="PILOTS_UNAVAILABLE" body={error.message} /></div>;
  }
  if (!response) return <div className="page-loading"><LoadingState label="Loading pilot registry" /></div>;
  if (!response.data.length) {
    return <div className="page-loading"><EmptyState title="No active pilots" body="The pilot registry returned no locations." /></div>;
  }
  if (!value) return <div className="page-loading"><LoadingState label="Resolving pilot" /></div>;
  return <PilotContext.Provider value={value}>{children}</PilotContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- provider and hook form one boundary
export function usePilot() {
  const value = useContext(PilotContext);
  if (!value) throw new Error("usePilot must be used inside PilotProvider");
  return value;
}
