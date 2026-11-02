// Service Worker for VoiceFi Mobile Companion PWA (Offline Conference Ready)
const CACHE_NAME = 'voicefi-companion-v122';
const APP_SHELL_URLS = ['/', '/manifest.json', '/api/icon'];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL_URLS).catch(() => {});
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => (key !== CACHE_NAME ? caches.delete(key) : Promise.resolve()))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  const url = event.request.url || '';

  // Pass WebSocket, live API calls (except /api/icon), and Downloads straight to network
  if (
    url.includes('/ws') ||
    (url.includes('/api/') && !url.includes('/api/icon')) ||
    url.includes('/downloads')
  ) {
    return;
  }

  // Document navigation: Network-first with Offline App Shell cache fallback
  if (event.request.mode === 'navigate' || event.request.destination === 'document') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put('/', copy.clone());
              cache.put(event.request, copy);
            });
          }
          return response;
        })
        .catch(async () => {
          const cachedDoc = await caches.match(event.request);
          if (cachedDoc) return cachedDoc;
          return caches.match('/');
        })
    );
    return;
  }

  // Static assets & CDN scripts: Network-first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200 && (response.type === 'basic' || response.type === 'cors')) {
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
