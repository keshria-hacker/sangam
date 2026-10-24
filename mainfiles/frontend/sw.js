/**
 * Sangam service worker — fresh-first (Phase 5).
 *
 * - API calls (/api/*): network-only, never cached.
 * - Static assets (css/js/fonts/icons): NETWORK-first,
 *   fall back to the cache when offline. This guarantees UI updates
 *   are visible after a normal reload — no stale cache pinning.
 * - Versioned cache; old caches purged on activate.
 */
const CACHE = 'sangam-v2';
const STATIC_PATTERNS = [
  /\/css\//, /\/js\//, /\/assets\//, /favicon\.ico$/,
  /fonts\.googleapis\.com/, /cdnjs\.cloudflare\.com/, /cdn\.jsdelivr\.net/,
];

self.addEventListener('install', (event) => {
  // Skip waiting so updates apply promptly
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Never cache API traffic (also never fail offline on it)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  const isStatic = STATIC_PATTERNS.some((re) => re.test(url.href)) ||
    url.origin === self.location.origin;

  if (isStatic) {
    // Network-first: always fresh when online, cache as offline fallback
    event.respondWith(
      fetch(request)
        .then((resp) => {
          // Cache only successful same-origin responses
          if (resp && resp.ok && url.origin === self.location.origin) {
            const clone = resp.clone();
            caches.open(CACHE).then((cache) => cache.put(request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(request).then((cached) => cached || Response.error()))
    );
  }
  // Non-static, non-API: default browser behavior (no interception)
});
