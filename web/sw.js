// Minimal Service Worker for PWA installability (network-first, no stale cache).
// 이 사이트 자신의 GET 요청만 거친다. 로컬 에이전트(127.0.0.1:18080) 같은 다른 출처 요청은
// 브라우저가 직접 처리하도록 손대지 않는다 (CORS·로컬 네트워크 권한 판단을 바꾸지 않기 위해).
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  if (new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith(fetch(event.request));
});
