const CACHE_NAME = 'chess-analyzer-mobile-v1';
const ASSETS = ['/', '/src/app.js', '/src/styles.css', '/manifest.webmanifest', '/stockfish-worker.js'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).catch(() => undefined));
});
self.addEventListener('fetch', event => {
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
