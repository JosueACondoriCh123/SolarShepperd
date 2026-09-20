const CACHE = "solarshepherd-shared-v3";
const SHELL = ["/", "/app/jkuat/dashboard", "/manifest.webmanifest", "/solarshepherd-icon.svg"];
const SHARED_API_PATHS = [
  "/api/v1/telemetry",
  "/api/v1/forecast",
  "/api/v1/scenes",
  "/api/v1/cells",
  "/api/v1/pilots",
  "/api/v1/calibration/status",
];

const PRIVATE_API_PREFIXES = [
  "/api/v1/missions",
  "/api/v1/sample-submissions",
  "/api/v1/reports",
  "/api/v1/me",
  "/api/v1/alerts",
  "/api/v1/alert-rules",
  "/api/v1/admin",
  "/api/v1/routes",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Explicitly protect all private API routes: NEVER intercept or store in Cache Storage
  const isPrivateApi = PRIVATE_API_PREFIXES.some(
    (prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`)
  );
  if (isPrivateApi) {
    // Network-only. Never store in cache, never fall back to cache.
    return;
  }

  const cacheableApi = SHARED_API_PATHS.some(
    (path) => url.pathname === path || url.pathname.startsWith(`${path}/`)
  );

  if (cacheableApi) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Any other API path that is not shared should not fall back to application shell
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // Shell & static navigation assets on same origin
  if (url.origin === self.location.origin) {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(request).then((cached) => cached || caches.match("/"))
      )
    );
  }
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SOLARSHEPHERD_SIGNOUT") {
    event.waitUntil(
      caches.keys().then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
    );
  }
});
