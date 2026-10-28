// Service worker de la app "Excavadora de Juan": permite instalarla y abrirla rápido.
// Solo guarda la propia página; la API y el WebSocket siempre van a la red.
const CACHE = "excavadora-v1";
const ARCHIVOS = ["./", "./index.html", "./manifest.webmanifest", "./icono-192.png", "./icono-512.png"];
const ALCANCE = new URL("./", self.location).pathname;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Red primero (para ver siempre la versión nueva); sin red, la copia guardada
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith(ALCANCE)) return;
  e.respondWith(
    fetch(e.request)
      .then(r => { const copia = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request).then(r => r || caches.match("./index.html")))
  );
});
