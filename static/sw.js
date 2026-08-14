// Dispatch Scheduler service worker.
// v2: adds offline READ — successful page navigations are cached so the
// app stays viewable when PythonAnywhere is unreachable. API calls are
// never cached here (the app's offline-write queue owns that in Phase 2);
// a failed API call returns a 503 the page can detect.
const STATIC_CACHE = 'dispatch-static-v2';
const PAGE_CACHE   = 'dispatch-pages-v1';
const STATIC = [
  '/static/css/main.css',
  '/static/icons/icon.svg',
  '/static/manifest.json',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC_CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  const keep = [STATIC_CACHE, PAGE_CACHE];
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => !keep.includes(k)).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── On-demand page pre-caching ("Prepare Offline") ─────────────────────
// A page's own fetch() is mode:'cors'/'same-origin', never 'navigate', so
// the navigate branch below can't capture it. The client instead posts the
// URLs it wants available offline and we cache them here, then report each
// result back so the UI can show ✓/✗ per day.
self.addEventListener('message', e => {
  const d = e.data || {};
  if (d.type !== 'PRECACHE_PAGES' || !Array.isArray(d.urls)) return;
  e.waitUntil((async () => {
    const cache = await caches.open(PAGE_CACHE);
    const results = [];
    for (const u of d.urls) {
      try {
        // credentials: the session cookie must ride along or we'd cache
        // a login redirect instead of the real page.
        const res = await fetch(u, { credentials: 'same-origin', cache: 'reload' });
        if (res.ok && !res.redirected) {
          await cache.put(u, res.clone());
          results.push({ url: u, ok: true });
        } else {
          results.push({ url: u, ok: false, status: res.status,
                         redirected: res.redirected });
        }
      } catch (err) {
        results.push({ url: u, ok: false, error: String(err) });
      }
    }
    if (e.source) e.source.postMessage({ type: 'PRECACHE_DONE', results });
  })());
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;   // never touch POST/PUT/DELETE
  const url = new URL(e.request.url);

  // API GETs: network only. On failure hand back a 503 the app recognises
  // as "server down" (so it can switch to offline mode / cached data).
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ ok: false, offline: true }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }

  // Page navigations: network-first, cache the good HTML, fall back to
  // the last cached copy of that page when the server is unreachable.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then(res => {
        // Only cache a real, non-redirected page (a redirect to /login
        // when the session expired must never be cached as the page).
        if (res.ok && !res.redirected && res.type === 'basic') {
          const clone = res.clone();
          caches.open(PAGE_CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() =>
        // ignoreVary: Flask stamps session responses with "Vary: Cookie",
        // which would make an otherwise-good cache entry miss (e.g. after
        // the session cookie is refreshed). The URL is identity enough here.
        caches.match(e.request, { ignoreVary: true }).then(cached =>
          cached || new Response(
            '<!doctype html><meta charset="utf-8">' +
            '<title>Offline</title><body style="font-family:sans-serif;' +
            'text-align:center;padding:60px;color:#5A0F1C;">' +
            '<h2>Offline</h2><p>Hindi pa nabubuksan ang page na ito habang ' +
            'may koneksyon, kaya wala pang naka-save na kopya. Bumalik sa ' +
            'isang page na nabuksan mo na kanina.</p></body>',
            { headers: { 'Content-Type': 'text/html' }, status: 200 }))
      )
    );
    return;
  }

  // Everything else (CSS/JS/icons): cache-first.
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(STATIC_CACHE).then(c => c.put(e.request, clone));
        return res;
      });
    })
  );
});
