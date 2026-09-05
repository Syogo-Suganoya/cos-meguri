/* 会場は電波が悪い。シェルだけ先にキャッシュして、APIは常にネットワークを見る。 */

const CACHE = "cos-meguri-v16";

// ページとモジュールを両方いれる。ここに実在しないURLが混じると install が
// 丸ごと失敗するので、tests/test_web_shell.py で全部 200 になることを見ている。
const SHELL = [
  "/",
  "/prep",
  "/plan",
  "/looks",
  "/day",
  "/static/style.css?v=39",
  "/static/js/core/dom.js",
  "/static/js/core/api.js",
  "/static/js/core/store.js",
  "/static/js/core/auth.js",
  "/static/js/core/shell.js",
  "/static/js/core/inbox.js",
  "/static/js/core/chat.js",
  "/static/js/core/expedition.js",
  "/static/js/core/media.js",
  "/static/js/pages/home.js",
  "/static/js/pages/prep.js",
  "/static/js/pages/plan.js",
  "/static/js/pages/looks.js",
  "/static/js/pages/day.js",
  "/static/icon.svg",
  "/favicon.svg",
  "/apple-touch-icon.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // addAll は1つでも失敗すると全部落ちる。1枚欠けただけでオフライン能力を
      // 丸ごと失わないよう、入るものから入れる
      .then((c) => Promise.allSettled(SHELL.map((url) => c.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // API 応答はキャッシュしない（進捗・混雑・位置は鮮度が命）
  if (url.pathname.startsWith("/api/")) return;

  // ページはネットワーク優先。キャッシュ優先にすると、デプロイしても
  // 古いビルドに固定されたままになる
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(request).then((hit) => hit || caches.match("/")))
    );
    return;
  }

  // 静的ファイルはキャッシュを先に返しつつ、裏で取り直して次回に備える。
  // JS モジュールは URL にバージョンを付けられないので、CACHE 名の更新を
  // 忘れても1回ぶん遅れで自然に新しくなるようにしておく
  event.respondWith(
    caches.match(request).then((hit) => {
      const network = fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
          return res;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});
