/* ログインの入口。

   相談とプランはログインしなくても使える。通行証を持っていない人には、
   Firebase の匿名ログインでゲストの通行証を取って渡す（サーバはゲストにも条件と
   プランの置き場所を作る）。お気に入りとマイページは、ログインした人だけが使える。

   ゲストのあいだに組んだプランは、ログインや登録をした直後に本人へ移す（adoptGuest）。 */

import { api, refreshSession } from "./api.js";
import * as store from "./store.js";
import { t } from "./i18n.js";

export const authConfig = () => store.cached("cos-meguri.authcfg", () => api("/api/auth/config", { auth: false }));

/** ゲストの通行証を取る。メールもパスワードも付けずに登録の REST を叩くと、匿名のアカウントになる。 */
async function startGuest() {
  const cfg = await authConfig();
  const tokens = await firebaseToken(cfg.sign_up_url, { apiKey: cfg.api_key });
  store.setTokens({ ...tokens, guest: true });
}

/** 相談とプラン。ログインしていなければゲストとして通す。 */
export async function requireSession() {
  const toLogin = () => {
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    return new Promise(() => {}); // 遷移するので、ここから先は動かさない
  };
  if (!store.token()) {
    try {
      await startGuest();
    } catch {
      // ゲストの通行証も取れない（認証の相手に届かないなど）。ログインの画面なら理由を出せる
      store.clearSession();
      return toLogin();
    }
  }
  try {
    return await api("/api/auth/session", { method: "POST" });
  } catch (err) {
    // 期限切れなら行き先は api.js が決めてある。それ以外（サーバの不調）は通行証を消さない。
    // ゲストの通行証を消すと、組んだプランの持ち主が分からなくなる
    return err.lost ? new Promise(() => {}) : toLogin();
  }
}

/** マイページ。ログインしていない人（ゲストを含む）はログインへ送り、戻り先を持たせる。 */
export async function requireMember() {
  if (!store.isMember()) {
    location.href = `/login?need=member&next=${encodeURIComponent(location.pathname)}`;
    return new Promise(() => {});
  }
  const layer = await requireSession();
  if (layer.guest) {
    store.clearSession();
    location.href = `/login?need=member&next=${encodeURIComponent(location.pathname)}`;
    return new Promise(() => {});
  }
  return layer;
}

/**
 * ログインや登録で得た通行証に切り替える。ゲストだったなら、組んだプランを引き取る。
 * 引き取りに失敗しても、ログイン自体は成り立っているので止めない。
 */
export async function startSession(tokens) {
  let guestToken = null;
  if (store.isGuest()) {
    // ゲストの通行証が切れていると引き取りを断られる。切り替える前に更新しておく
    await refreshSession();
    guestToken = store.token();
  }
  store.setTokens({ ...tokens, guest: false });
  const layer = await api("/api/auth/session", { method: "POST" });
  if (guestToken) {
    await api("/api/auth/adopt", { method: "POST", body: { guest_token: guestToken } }).catch(() => {});
  }
  return layer;
}

export function logout() {
  store.clearSession();
  location.href = "/";
}

/**
 * Firebase は Identity Toolkit の REST を直接叩く。SDK も CDN も使わない。
 * email と password を渡さなければ、ゲスト（匿名）の通行証が返る。
 */
export async function firebaseToken(url, { email, password, apiKey }) {
  const body = email === undefined ? { returnSecureToken: true } : { email, password, returnSecureToken: true };
  const res = await fetch(`${url}?key=${encodeURIComponent(apiKey)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message || t("ログインできませんでした"));
  return { idToken: data.idToken, refreshToken: data.refreshToken };
}
