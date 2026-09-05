/* トップ。何ができるアプリかを先に伝え、その下でログインする。 */

import { $, msg, on } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { authConfig, firebaseToken, startSession } from "./../core/auth.js";
import { mountShell } from "./../core/shell.js";
import * as store from "./../core/store.js";

const cfg = await authConfig();
const signedIn = Boolean(store.token());

let layer = null;
if (signedIn) {
  try {
    layer = await api("/api/auth/session", { method: "POST", body: { handle: null } });
  } catch {
    store.clearSession();
  }
}

// トップは案内のページ。左のステップ帯は置かない
await mountShell({ authed: Boolean(layer), layer, rail: false });

if (new URLSearchParams(location.search).get("expired")) {
  msg($("login-error"), "ログインの期限が切れました。もう一度入りなおしてください。", "alert");
}

// ---- ログイン中と未ログインで、入口の見せ方を変える ----

// 開発用ログインはコス名だけで成立する。入口にフォームは置かず、
// 端末ごとに違う仮のコス名でそのまま始めてもらう（本番はメール認証の欄に切り替わる）。
//
// 固定のコス名にすると、開発トークンの uid が uuid5(コス名) で決まるせいで
// 「はじめる」を押した全員が同じアカウントに入ってしまう。あとで名前を
// 変えたいときは 準備 のページから変える。
function deviceHandle() {
  const kept = store.loginHandle();
  if (kept) return { handle: kept, fresh: false };

  const bytes = new Uint8Array(3);
  // localhost や https では crypto を使う。それ以外へ置いたときの保険も持つ
  if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
  else bytes.forEach((_, i) => (bytes[i] = Math.floor(Math.random() * 256)));

  const tag = [...bytes].map((n) => n.toString(16).padStart(2, "0")).join("").toUpperCase();
  const handle = `レイヤー${tag}`;
  store.setLoginHandle(handle);
  return { handle, fresh: true };
}

if (layer) {
  // 入っている人には「はじめる」ではなく、続きへの入口を出す
  const cta = $("btn-dev-login");
  cta.textContent = "つづきをひらく";
  cta.onclick = () => (location.href = "/prep");
} else if (cfg.provider === "firebase") {
  $("btn-dev-login").classList.add("hidden");
  $("view-login").classList.remove("hidden");
}

// ---- ログイン ----

function goNext() {
  const next = new URLSearchParams(location.search).get("next");
  location.href = next && next.startsWith("/") ? next : "/prep";
}

on("btn-dev-login", "click", async () => {
  if (layer) return; // 上で行き先を差し替えてある
  const { handle, fresh } = deviceHandle();
  try {
    const res = await api("/api/auth/dev-login", { method: "POST", body: { handle }, auth: false });
    // 2回目以降はコス名を送らない。あとで変えた名前を仮の名前で上書きしないため
    await startSession(res.token, fresh ? handle : null);
    goNext();
  } catch (err) {
    msg($("login-error"), err.message, "error");
  }
});

async function firebaseLogin(url) {
  try {
    const token = await firebaseToken(url, {
      email: $("fb-email").value.trim(),
      password: $("fb-password").value,
      apiKey: cfg.api_key,
    });
    await startSession(token, $("fb-handle").value.trim());
    goNext();
  } catch (err) {
    msg($("login-error"), err.message, "error");
  }
}

on("btn-fb-login", "click", () => firebaseLogin(cfg.sign_in_url));
on("btn-fb-signup", "click", () => firebaseLogin(cfg.sign_up_url));

// ---- 飛沫の層をずらして動かす ----
//
// スクロール量とポインタ位置に data-depth を掛けるだけ。奥のものほど動かない。
// 動きを減らす設定の人には何もしない（飾りなので、無くても内容は変わらない）。

const wantsMotion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
const layers = [...document.querySelectorAll(".deco [data-depth]")].map((el) => ({
  el,
  depth: Number(el.dataset.depth) || 0,
  // CSS で傾けてあるぶんは保ったまま平行移動を足す
  base: getComputedStyle(el).transform === "none" ? "" : getComputedStyle(el).transform,
}));

if (wantsMotion && layers.length) {
  let scrollY = 0;
  let pointerX = 0;
  let pointerY = 0;
  let queued = false;

  const paint = () => {
    queued = false;
    for (const { el, depth, base } of layers) {
      const y = -scrollY * depth * 0.55 + pointerY * depth * 14;
      const x = pointerX * depth * 22;
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) ${base}`;
    }
  };

  const request = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(paint);
  };

  addEventListener(
    "scroll",
    () => {
      scrollY = window.scrollY;
      request();
    },
    { passive: true }
  );

  addEventListener(
    "pointermove",
    (e) => {
      // 画面の中心を 0 として -1〜1 に均す
      pointerX = (e.clientX / innerWidth) * 2 - 1;
      pointerY = (e.clientY / innerHeight) * 2 - 1;
      request();
    },
    { passive: true }
  );

  paint();
}
