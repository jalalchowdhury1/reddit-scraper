const CACHE_NAME = 'daily-reader-v1';
const ASSETS = [
  './',
  './index.html',
  './manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      const fetchPromise = fetch(e.request).then((networkResponse) => {
        caches.open(CACHE_NAME).then((cache) => {
          // Only cache valid GET requests
          if (e.request.method === 'GET' && networkResponse.status === 200) {
            cache.put(e.request, networkResponse.clone());
          }
        });
        return networkResponse;
      }).catch(() => cachedResponse); // Fallback to cache if offline
      
      return cachedResponse || fetchPromise;
    })
  );
});