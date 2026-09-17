/* 会場は電波が悪い。シェルだけ先にキャッシュして、APIは常にネットワークを見る。 */

const CACHE = "cos-meguri-v59";

// ページとモジュールを両方いれる。ここに実在しないURLが混じると install が
// 丸ごと失敗するので、tests/test_web_shell.py で全部 200 になることを見ている。
const SHELL = [
  "/",
  "/ask",
  "/login",
  "/signup",
  "/plan",
  "/me",
  "/static/style.css?v=82",
  "/static/js/core/dom.js",
  "/static/js/core/api.js",
  "/static/js/core/store.js",
  "/static/js/core/auth.js",
  "/static/js/core/shell.js",
  "/static/js/core/expedition.js",
  "/static/js/core/credentials.js",
  "/static/js/core/en.js",
  "/static/js/core/i18n.js",
  "/static/js/core/favorites.js",
  "/static/js/pages/ask.js",
  "/static/js/pages/home.js",
  "/static/js/pages/login.js",
  "/static/js/pages/signup.js",
  "/static/js/pages/plan.js",
  "/static/js/pages/me.js",
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
  // API 応答はキャッシュしない（プランは組み直すたびに変わる）
  if (url.pathname.startsWith("/api/")) return;

  // ページも静的ファイルもネットワーク優先。繋がらないときだけキャッシュを返す。
  //
  // 以前は静的ファイルをキャッシュ優先（裏で取り直す）にしていたが、JS モジュールは
  // URL にバージョンを付けられないので、直しても「1回ぶん遅れて」しか届かなかった。
  // 消したはずのフッターがリロードしても残る、まで行ったのでやめた。サーバは ETag を
  // 返しているので、変わっていなければ 304 で済み、電波の悪い会場でも重くならない
  event.respondWith(
    fetch(request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() =>
        caches
          .match(request)
          .then((hit) => hit || (request.mode === "navigate" ? caches.match("/") : Response.error()))
      )
  );
});
