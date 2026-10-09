/**
 * Sangam service worker — simple and safe (Phase 5).
 *
 * - Static assets (css/js/fonts/icons): cache-first, fall back to network.
 * - API calls (/api/*): network-first, never cached.
 * - Versioned cache; old caches purged on activate.
 */
const CACHE = 'sangam-v1';
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

  // Never cache API traffic
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  const isStatic = STATIC_PATTERNS.some((re) => re.test(url.href)) ||
    url.origin === self.location.origin;

  if (isStatic) {
    // Cache-first for static assets
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((resp) => {
          if (resp && resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE).then((cache) => cache.put(request, clone));
          }
          return resp;
        });
      })
    );
  }
  // Non-static, non-API: default browser behavior (no interception)
});
