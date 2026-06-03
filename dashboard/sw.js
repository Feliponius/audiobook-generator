// Audiobook Library — Service Worker
// Caches: app shell, chapter audio (user-requested), book pages + covers, EPUBs, voice samples
// Strategy: shell=precache, audio=explicit, pages=network-first, EPUBs=explicit

const CACHE_SHELL = 'audiobooks-shell-v7';
const CACHE_CHAPTERS = 'audiobooks-chapters-v2';
const CACHE_PAGES = 'audiobooks-pages-v1';      // book detail API + cover images
const CACHE_EPUBS = 'audiobooks-epubs-v1';       // saved EPUB files
const CACHE_SAMPLES = 'audiobooks-samples-v2';

const SHELL_URLS = [
  '/',
  '/manifest.webmanifest',
  '/assets/app-icon-192.png',
  '/assets/app-icon-512.png',
  '/assets/app-icon.svg',
];

// CDN scripts needed for offline use — precached with no-cors
const CDN_URLS = [
  'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js',
  'https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js',
  'https://cdn.jsdelivr.net/npm/hls.js@1.5.7/dist/hls.min.js',
];

// ── Install: precache shell + CDN scripts ─────────────────────────────────
self.addEventListener('install', (ev) => {
  ev.waitUntil(
    caches.open(CACHE_SHELL).then(async (cache) => {
      await cache.addAll(SHELL_URLS);
      // Precache CDN scripts individually (cross-origin, no-cors)
      for (const url of CDN_URLS) {
        try {
          const resp = await fetch(url, { mode: 'no-cors' });
          if (resp.ok || resp.type === 'opaque') {
            await cache.put(url, resp);
          }
        } catch (_) { /* CDN unreachable — will cache on first networkFirst */ }
      }
    })
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ───────────────────────────────────────────
self.addEventListener('activate', (ev) => {
  ev.waitUntil(
    caches.keys().then((keys) => {
      const keep = new Set([CACHE_SHELL, CACHE_CHAPTERS, CACHE_PAGES, CACHE_EPUBS, CACHE_SAMPLES]);
      return Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k)));
    })
  );
  self.clients.claim();
});

// ── Fetch: routing ───────────────────────────────────────────────────────
self.addEventListener('fetch', (ev) => {
  const url = new URL(ev.request.url);
  const path = url.pathname;

  // ── HTML pages (shell): network-first, cache fallback ─────────────────
  if (ev.request.destination === 'document') {
    ev.respondWith(networkFirst(ev.request, CACHE_SHELL));
    return;
  }

  // ── Book detail API: network-first, cache for offline ─────────────────
  if (path === '/api/library/book') {
    ev.respondWith(networkFirst(ev.request, CACHE_PAGES));
    return;
  }

  // ── Library list API: network-first, cache briefly ────────────────────
  if (path === '/api/library') {
    ev.respondWith(networkFirst(ev.request, CACHE_PAGES));
    return;
  }

  // ── Cover / EPUB images: network-first, cache for offline ─────────────
  if (path === '/media') {
    const paramPath = url.searchParams.get('path');
    if (paramPath) {
      // Cover images and EPUB files
      if (/\.(png|jpg|jpeg|webp|svg|ico)$/i.test(paramPath)) {
        ev.respondWith(networkFirst(ev.request, CACHE_PAGES));
        return;
      }
      // EPUB files: explicit cache only (user saves them)
      if (/\.epub$/i.test(paramPath)) {
        ev.respondWith(cacheFirst(ev.request, CACHE_EPUBS).then(cached => cached || fetch(ev.request)));
        return;
      }
      // Chapter / final audio: explicit cache-first
      if (/\.(wav|mp3|m4a|m4b|m3u8|ts)$/i.test(paramPath)) {
        ev.respondWith(chapterAudioStrategy(ev.request));
        return;
      }
    }
  }

  // ── Voice samples: network-first, cache briefly ───────────────────────
  if (path === '/api/voices/sample') {
    ev.respondWith(networkFirst(ev.request, CACHE_SAMPLES));
    return;
  }

  // ── Other API: network-first, cache fallback ───────────────────────────
  if (path.startsWith('/api/')) {
    ev.respondWith(networkFirst(ev.request, CACHE_PAGES));
    return;
  }

  // ── Static assets: cache-first ─────────────────────────────────────────
  if (path.startsWith('/assets/') || path.endsWith('.svg') || path.endsWith('.png') || path.endsWith('.ico')) {
    ev.respondWith(cacheFirst(ev.request, CACHE_SHELL));
    return;
  }

  // ── Everything else: network-first ─────────────────────────────────────
  ev.respondWith(networkFirst(ev.request, CACHE_SHELL));
});

// ── Message handler: request-response via MessageChannel ports ───────────
self.addEventListener('message', (ev) => {
  const { action, url, urls } = ev.data || {};
  const port = ev.ports && ev.ports[0];

  function respond(data) {
    if (port) port.postMessage(data);
  }

  if (action === 'cache-chapter' && url) {
    ev.waitUntil(
      cacheChapter(url)
        .then(() => respond({ ok: true, url }))
        .catch((err) => respond({ error: err.message || 'Cache failed' }))
    );
  } else if (action === 'cache-chapters' && urls) {
    ev.waitUntil(
      Promise.all(urls.map(u => cacheChapter(u).catch(e => ({ error: e.message, url: u }))))
        .then((results) => {
          const errors = results.filter(r => r && r.error);
          if (errors.length) respond({ error: errors.map(e => e.url + ': ' + e.error).join('; ') });
          else respond({ ok: true, urls });
        })
    );
  } else if (action === 'uncache-chapter' && url) {
    ev.waitUntil(
      uncacheChapter(url)
        .then(() => respond({ ok: true, url }))
        .catch((err) => respond({ error: err.message || 'Uncache failed' }))
    );
  } else if (action === 'uncache-chapters' && urls) {
    ev.waitUntil(
      Promise.all(urls.map(u => uncacheChapter(u)))
        .then(() => respond({ ok: true, urls }))
        .catch((err) => respond({ error: err.message || 'Uncache failed' }))
    );
  } else if (action === 'get-cached-chapters') {
    ev.waitUntil(
      getCachedUrls(CACHE_CHAPTERS)
        .then((cachedUrls) => respond({ urls: cachedUrls }))
        .catch((err) => respond({ error: err.message }))
    );
  } else if (action === 'clear-chapters') {
    ev.waitUntil(
      caches.delete(CACHE_CHAPTERS)
        .then(() => respond({ ok: true }))
        .catch((err) => respond({ error: err.message }))
    );
  } else if (action === 'cache-epub' && url) {
    ev.waitUntil(
      cacheEpub(url)
        .then(() => respond({ ok: true, url }))
        .catch((err) => respond({ error: err.message || 'EPUB cache failed' }))
    );
  } else if (action === 'uncache-epub' && url) {
    ev.waitUntil(
      uncacheEpub(url)
        .then(() => respond({ ok: true, url }))
        .catch((err) => respond({ error: err.message || 'EPUB uncache failed' }))
    );
  } else if (action === 'get-cached-epubs') {
    ev.waitUntil(
      getCachedUrls(CACHE_EPUBS)
        .then((cachedUrls) => respond({ urls: cachedUrls }))
        .catch((err) => respond({ error: err.message }))
    );
  } else if (action === 'get-stats') {
    ev.waitUntil(
      getCacheStats()
        .then((stats) => {
          if (port) port.postMessage(stats);
          self.clients.matchAll().then(clients => {
            clients.forEach(c => c.postMessage({ type: 'cache-stats', ...stats }));
          });
        })
        .catch((err) => { if (port) port.postMessage({ error: err.message }); })
    );
  }
});

// ── Strategies ───────────────────────────────────────────────────────────

function networkFirst(request, cacheName) {
  return fetch(request)
    .then((response) => {
      // Cache ok responses AND opaque cross-origin responses (status 0).
      // Opaque responses are common for CDN scripts — without caching them,
      // the app breaks on first offline visit.
      if (response.ok || response.type === 'opaque') {
        const cloned = response.clone();
        caches.open(cacheName).then((cache) => cache.put(request, cloned));
      }
      return response;
    })
    .catch(() => caches.match(request));
}

function cacheFirst(request, cacheName) {
  return caches.match(request).then((cached) => cached || fetch(request));
}

function chapterAudioStrategy(request) {
  // Native media elements use Range requests for large audiobooks and seeking.
  // The Cache API cannot safely synthesize partial-content responses from a
  // cached full file, so never satisfy Range requests from cache.
  if (request.headers.has('range')) return fetch(request);
  return caches.match(request, { cacheName: CACHE_CHAPTERS }).then((cached) => {
    if (cached) return cached;
    return fetch(request);
  });
}

// ── Chapter audio helpers ───────────────────────────────────────────────

async function cacheChapter(url) {
  const cache = await caches.open(CACHE_CHAPTERS);
  const request = new Request(url);
  const response = await fetch(request);
  if (!response.ok) throw new Error(`Failed to fetch ${url}: ${response.status}`);
  await cache.put(request, response);
}

async function uncacheChapter(url) {
  const cache = await caches.open(CACHE_CHAPTERS);
  await cache.delete(new Request(url));
}

// ── EPUB helpers ────────────────────────────────────────────────────────

async function cacheEpub(url) {
  const cache = await caches.open(CACHE_EPUBS);
  const request = new Request(url);
  const response = await fetch(request);
  if (!response.ok) throw new Error(`Failed to fetch EPUB ${url}: ${response.status}`);
  await cache.put(request, response);
}

async function uncacheEpub(url) {
  const cache = await caches.open(CACHE_EPUBS);
  await cache.delete(new Request(url));
}

// ── Generic helpers ─────────────────────────────────────────────────────

async function getCachedUrls(cacheName) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  return keys.map((r) => r.url);
}

async function getCacheStats() {
  const stats = {};
  for (const name of [CACHE_SHELL, CACHE_CHAPTERS, CACHE_PAGES, CACHE_EPUBS, CACHE_SAMPLES]) {
    const cache = await caches.open(name);
    const keys = await cache.keys();
    let totalSize = 0;
    for (const req of keys) {
      const resp = await cache.match(req);
      if (resp) {
        const blob = await resp.clone().blob();
        totalSize += blob.size;
      }
    }
    stats[name] = { count: keys.length, bytes: totalSize };
  }
  return stats;
}
