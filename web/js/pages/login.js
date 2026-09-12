/* ログイン。アプリ側の1画面として持つ（トップは案内だけにしてある）。

   通行証を持っていない人がアプリのページを開くと、auth.js がここへ送る。
   入ったあとは ?next= で元のページへ戻す。 */

import { $, msg, on } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { authConfig, firebaseToken, startSession } from "./../core/auth.js";
import { mountShell } from "./../core/shell.js";
import * as store from "./../core/store.js";

const cfg = await authConfig();

// もう入っているなら、ここに留める理由がない
if (store.token()) {
  try {
    await api("/api/auth/session", { method: "POST", body: { handle: null } });
    goNext();
  } catch {
    store.clearSession();
  }
}

await mountShell({ authed: false, rail: false });

if (new URLSearchParams(location.search).get("expired")) {
  msg($("login-error"), "ログインの期限が切れました。もう一度入りなおしてください。", "alert");
}

// 本番はメール認証の欄に差し替える
if (cfg.provider === "firebase") {
  $("view-dev").classList.add("hidden");
  $("view-firebase").classList.remove("hidden");
}

function goNext() {
  const next = new URLSearchParams(location.search).get("next");
  // 最初にやることは相談。準備（コス名）は後からでよい
  location.href = next && next.startsWith("/") ? next : "/ask";
}

// ---- 開発用ログイン ----

/** 端末ごとの仮のコス名。同じ端末なら次も同じ人に戻る。
 *
 * 固定のコス名にすると、開発トークンの uid が uuid5(コス名) で決まるせいで
 * 「はじめる」を押した全員が同じアカウントに入ってしまう。
 */
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

on("btn-dev-login", "click", async () => {
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

// ---- メールで入る（本番） ----

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
