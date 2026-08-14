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
          await cachePage(cache, u, res);
          results.push({ url: u, ok: true });
        } else {
          results.push({ url: u, ok: false, status: res.status,
                         redirected: res.redirected });
        }
      } catch (err) {
        results.push({ url: u, ok: false, error: String(err) });
      }
    }
    // reqId is echoed so a manual "Prepare Now" never resolves on the
    // reply of a background auto-prepare that happened to finish first.
    if (e.source) e.source.postMessage({ type: 'PRECACHE_DONE',
                                         reqId: d.reqId || null, results });
  })());
});


// Store a page in the cache with the time it was captured, so a later
// offline hit can tell the user HOW OLD the copy is.
async function cachePage(cache, request, res) {
  const buf = await res.clone().arrayBuffer();
  const headers = new Headers(res.headers);
  headers.set('X-SW-Cached-At', new Date().toISOString());
  await cache.put(request, new Response(buf, {
    status: res.status, statusText: res.statusText, headers }));
}

// Serve a cached page, stamping a <meta name="sw-cached-at"> into it. The
// page reads that meta and shows a "saved copy from <time>" banner —
// without it a stale cached page is indistinguishable from live data,
// which is how edits could look "lost" after reopening the app.
async function servePageFromCache(request) {
  const cached = await caches.match(request, { ignoreVary: true });
  if (!cached) return null;
  const ct = cached.headers.get('Content-Type') || '';
  if (!/text\/html/i.test(ct)) return cached;
  const at = cached.headers.get('X-SW-Cached-At') || '';
  let html = await cached.text();
  const meta = `<meta name="sw-cached-at" content="${at}">`;
  html = html.includes('</head>') ? html.replace('</head>', meta + '</head>')
                                  : meta + html;
  return new Response(html, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}


// Offline dead-end rescue: the requested page isn't cached (e.g. a date
// nobody opened while online, or the bare "/" which is a redirect and
// therefore never cached). Instead of a blank wall, list what IS
// available offline so the user can jump straight into it.
async function offlineIndexResponse() {
  let links = '';
  try {
    const cache = await caches.open(PAGE_CACHE);
    const paths = (await cache.keys())
      .map(r => new URL(r.url).pathname)
      .filter(p => p && p !== '/')
      .sort();
    links = paths.length
      ? paths.map(p => `<li><a href="${p}">${p}</a></li>`).join('')
      : '<li class="none">Wala pang naka-save na page sa device na ito.</li>';
  } catch (e) {
    links = '<li class="none">Hindi mabuksan ang offline storage.</li>';
  }
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline — Dispatch Scheduler</title><style>
 body{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:38px 22px;color:#2D1515;background:#F5F0F0}
 .card{max-width:620px;margin:0 auto;background:#fff;border:1px solid #E8D4D6;border-radius:14px;padding:26px 28px}
 h1{margin:0 0 6px;font-size:1.25rem;color:#5A0F1C}
 p{margin:0 0 14px;font-size:.92rem;line-height:1.5;color:#5A3A3A}
 ul{margin:0;padding-left:20px;font-size:.92rem} li{margin:5px 0}
 a{color:#5A0F1C;font-weight:600;text-decoration:none} a:hover{text-decoration:underline}
 .none{color:#9A7777;list-style:none;margin-left:-20px}
 .tip{margin-top:18px;font-size:.82rem;color:#9A7777;border-top:1px solid #E8D4D6;padding-top:12px}
 button{margin-top:16px;background:#5A0F1C;color:#fff;border:0;border-radius:8px;padding:9px 18px;font-size:.9rem;cursor:pointer}
</style></head><body><div class="card">
 <h1>Offline — walang koneksyon sa server</h1>
 <p>Hindi naka-save sa device na ito ang page na hinahanap mo. Eto ang
    mga <b>available offline</b> ngayon:</p>
 <ul>${links}</ul>
 <button onclick="location.reload()">Subukan ulit</button>
 <div class="tip">Tip: habang may internet, buksan ang Schedule at pindutin
   ang <b>Prepare Offline</b> — awtomatiko rin itong nag-se-save ng
   ngayon + susunod na 3 araw tuwing gagamitin mo ang app.</div>
</div></body></html>`,
    { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 200 });
}

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

  // Page navigations: network-first, cache the good HTML, fall back to the
  // last cached copy whenever the network can't give us a usable page.
  //
  // ignoreVary throughout: Flask stamps session responses with
  // "Vary: Cookie", which would make an otherwise-good cache entry miss
  // (e.g. after the session cookie is refreshed). The URL is identity
  // enough here.
  if (e.request.mode === 'navigate') {
    e.respondWith((async () => {
      try {
        const res = await fetch(e.request);
        if (res.ok && !res.redirected && res.type === 'basic') {
          const clone = res.clone();
          caches.open(PAGE_CACHE).then(c => cachePage(c, e.request, clone));
          return res;
        }
        // A redirect is a real answer (typically /login after the session
        // expired) — never mask it with a stale page, or the user gets
        // trapped on a schedule they can no longer save to.
        if (res.redirected) return res;
        // The server answered, but not with a usable page: 5xx, or an
        // empty/zero-status reply (this is what ERR_EMPTY_RESPONSE looks
        // like from a half-dead host). Previously this was passed straight
        // through, so a broken server beat a perfectly good cached copy —
        // the "This page isn't working" screen despite being prepared.
        return (await servePageFromCache(e.request)) || res;
      } catch (err) {
        // Hard network failure (truly offline, DNS, connection refused).
        return (await servePageFromCache(e.request)) || offlineIndexResponse();
      }
    })());
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
