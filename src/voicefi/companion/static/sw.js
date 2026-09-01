// Service Worker for VoiceFi Mobile Companion PWA
const CACHE_NAME = 'voicefi-companion-v15';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Pass WebSocket, API, Downloads, and Document navigation requests straight to live network
  if (
    event.request.mode === 'navigate' ||
    event.request.destination === 'document' ||
    event.request.url.includes('/ws') ||
    event.request.url.includes('/api/') ||
    event.request.url.includes('/downloads')
  ) {
    return;
  }

  // Network-first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200 && response.type === 'basic') {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
