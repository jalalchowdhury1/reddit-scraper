// Daily Reader service worker (v2, 2026-09-26; offline /api/data marked 2026-09-27).
// NETWORK-FIRST for everything: the old worker was cache-first, which would
// have shown yesterday's feed on open. Cache is only the offline fallback.
const CACHE_NAME = 'daily-reader-v2';
const SHELL = ['/', '/manifest.json', '/icon.png'];
// The CDN files the page needs to work (25 Oct 2026): Firebase sync and the Phosphor
// icons. Their URLs pin a version, so they never change: cache-first, in their own cache
// (CACHE_NAME holds his saved feed and must survive every deploy).
const ASSET_CACHE = 'daily-reader-assets-v1';
const FB = 'https://www.gstatic.com/firebasejs/10.8.0/';
const PH = 'https://cdn.jsdelivr.net/npm/@phosphor-icons/web@2.1.1/src/';
const ASSETS = [FB + 'firebase-app-compat.js', FB + 'firebase-auth-compat.js', FB + 'firebase-firestore-compat.js',
                PH + 'regular/style.css', PH + 'regular/Phosphor.woff2', PH + 'fill/style.css', PH + 'fill/Phosphor-Fill.woff2'];
const SLOW_MS = 8000;   // weak signal: after this, the saved copy instead of a spinner

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(Promise.all([
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL)).catch(() => {}),
    caches.open(ASSET_CACHE).then((c) => c.addAll(ASSETS)).catch(() => {}),
  ]));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME && k !== ASSET_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.href.startsWith(FB) || url.href.startsWith(PH)) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(ASSET_CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    })));
    return;
  }
  if (url.origin !== self.location.origin) return;
  // The saved copy, marked so the page can say it's not fresh
  // (pull-to-refresh must not claim "Refreshed" from a saved copy).
  const saved = () => caches.match(e.request).then((r) => {
    if (!r || url.pathname !== '/api/data') return r;
    const h = new Headers(r.headers);
    h.set('X-Offline-Copy', '1');
    return new Response(r.body, { status: r.status, statusText: r.statusText, headers: h });
  });
  const network = fetch(e.request).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      return caches.open(CACHE_NAME).then((c) => c.put(e.request, copy)).then(() => res, () => res);
    }
    return res;
  });
  e.waitUntil(network.catch(() => {}));   // a late answer still refreshes the saved copy
  e.respondWith(new Promise((resolve) => {
    let done = false;
    const give = (r) => { if (!done) { done = true; resolve(r); } };
    // Weak signal: the saved copy after SLOW_MS (only if there is one; else keep waiting).
    if (url.pathname === '/api/data' || e.request.mode === 'navigate') {
      setTimeout(() => saved().then((r) => r && give(r)), SLOW_MS);
    }
    network
      // The server failed (a Vercel pause is 503 DEPLOYMENT_PAUSED, a crash 500, a timeout 504):
      // the saved copy if there is one, else the real error.
      .then((res) => (res.status >= 500 ? saved().then((r) => give(r || res)) : give(res)))
      .catch(() => saved().then(give));   // offline
  }));
});
