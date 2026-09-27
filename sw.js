// Daily Reader service worker (v2, 2026-09-26; offline /api/data marked 2026-09-27).
// NETWORK-FIRST for everything: the old worker was cache-first, which would
// have shown yesterday's feed on open. Cache is only the offline fallback.
const CACHE_NAME = 'daily-reader-v2';
const SHELL = ['/', '/manifest.json', '/icon.png'];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      // Offline: the saved copy, marked so the page can say it's not fresh
      // (pull-to-refresh must not claim "Refreshed" from a saved copy).
      .catch(() => caches.match(e.request).then((r) => {
        if (!r || url.pathname !== '/api/data') return r;
        const h = new Headers(r.headers);
        h.set('X-Offline-Copy', '1');
        return new Response(r.body, { status: r.status, statusText: r.statusText, headers: h });
      }))
  );
});
