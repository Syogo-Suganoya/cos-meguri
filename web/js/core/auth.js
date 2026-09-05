/* ログインの入口。画面は /login だけが持ち、他のページは通行証を確かめるだけ。 */

import { api } from "./api.js";
import * as store from "./store.js";

export const authConfig = () => store.cached("cos-meguri.authcfg", () => api("/api/auth/config", { auth: false }));

/** ログイン済みのレイヤーを返す。通行証が無ければトップへ戻す。 */
export async function requireSession() {
  if (!store.token()) {
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    return new Promise(() => {}); // 遷移するので、ここから先は動かさない
  }
  try {
    return await api("/api/auth/session", { method: "POST", body: { handle: null } });
  } catch {
    store.clearSession();
    location.href = "/";
    return new Promise(() => {});
  }
}

/** ログイン画面だけが使う。入ってから、来たかったページへ送る。 */
export async function startSession(token, handle) {
  store.setToken(token);
  const layer = await api("/api/auth/session", { method: "POST", body: { handle: handle || null } });
  return layer;
}

export function logout() {
  store.clearSession();
  location.href = "/";
}

/** Firebase は Identity Toolkit の REST を直接叩く。SDK も CDN も使わない。 */
export async function firebaseToken(url, { email, password, apiKey }) {
  const res = await fetch(`${url}?key=${encodeURIComponent(apiKey)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, returnSecureToken: true }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message || "ログインできませんでした");
  return data.idToken;
}
