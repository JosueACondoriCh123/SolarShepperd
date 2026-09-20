import type { ApiErrorShape } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  code: string;
  details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

let accessTokenProvider: () => Promise<string | null> = async () => null;
let activePilotSlug: string | null = null;
const activeRequests = new Set<AbortController>();

export function setAccessTokenProvider(provider: () => Promise<string | null>) {
  accessTokenProvider = provider;
}

export function setActivePilotSlug(slug: string | null) {
  if (activePilotSlug === slug) return;
  activePilotSlug = slug;
  activeRequests.forEach((controller) => controller.abort());
  activeRequests.clear();
}

function withPilot(path: string) {
  if (!activePilotSlug || path === "/pilots" || path.startsWith("/pilots/")) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}pilot=${encodeURIComponent(activePilotSlug)}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await accessTokenProvider();
  const formData = init?.body instanceof FormData;
  const controller = new AbortController();
  activeRequests.add(controller);
  const response = await fetch(`${API_BASE}${withPilot(path)}`, {
    ...init,
    signal: controller.signal,
    headers: {
      ...(formData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  }).finally(() => activeRequests.delete(controller));
  if (!response.ok) {
    let body: ApiErrorShape = {};
    try {
      body = (await response.json()) as ApiErrorShape;
    } catch {
      // Preserve the HTTP status when an upstream gateway returns non-JSON.
    }
    throw new ApiError(
      body.error?.code || `HTTP_${response.status}`,
      body.error?.message || `Request failed with status ${response.status}.`,
      body.error?.details,
    );
  }
  const syncedAt = new Date().toISOString();
  localStorage.setItem("solarshepherd-last-sync", syncedAt);
  window.dispatchEvent(new CustomEvent("solarshepherd-sync", { detail: syncedAt }));
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export async function apiDownload(path: string, filename: string): Promise<void> {
  const token = await accessTokenProvider();
  const response = await fetch(`${API_BASE}${withPilot(path)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    let body: ApiErrorShape = {};
    try {
      body = (await response.json()) as ApiErrorShape;
    } catch {
      // Gateways may return HTML for an upstream failure.
    }
    throw new ApiError(
      body.error?.code || `HTTP_${response.status}`,
      body.error?.message || `Download failed with status ${response.status}.`,
      body.error?.details,
    );
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export const apiGet = <T,>(path: string) => request<T>(path);
export const apiPost = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const apiPatch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const apiDelete = (path: string) => request<void>(path, { method: "DELETE" });
export const apiUpload = <T,>(path: string, file: File) => {
  const body = new FormData();
  body.append("file", file);
  return request<T>(path, { method: "POST", body });
};
