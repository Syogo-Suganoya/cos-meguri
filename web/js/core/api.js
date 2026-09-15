/* API 呼び出し。持つのは ID トークン（と更新用のトークン）だけで、パスワードは保持しない。 */

import * as store from "./store.js";
import { t } from "./i18n.js";

// サーバの誤りの印（detail.code）→ 画面の言語での言い方。サーバの文面は日本語のまま届く
const ERROR_CODES = {
  guest: "お気に入りはログインすると使えます",
  favorites_limit: "お気に入りは{limit}件までです。マイページで要らないものを消してください",
  ends_before_starts: "終了は開始より後の時刻にしてください。",
  bad_time: "時刻は HH:MM の形で入れてください。",
};

const authConfig = () => store.cached("cos-meguri.authcfg", () => api("/api/auth/config", { auth: false }));

/**
 * 通行証を更新する。更新できたら true。
 *
 * ID トークンは1時間で切れる。ゲストは入り直す手段が無いので、切れたら更新しないと
 * 組んだプランごと見失う。同時に何本も切れても、更新は1回にまとめる。
 */
let refreshing = null;
export function refreshSession() {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => (refreshing = null));
  }
  return refreshing;
}

async function doRefresh() {
  const refreshToken = store.refreshToken();
  if (!refreshToken) return false;
  try {
    const cfg = await authConfig();
    if (!cfg.refresh_url) return false;
    const res = await fetch(`${cfg.refresh_url}?key=${encodeURIComponent(cfg.api_key)}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    store.renewTokens({ idToken: data.id_token, refreshToken: data.refresh_token });
    return true;
  } catch {
    return false;
  }
}

/** 更新しても通らなかったとき。ゲストは新しいゲストで開き直し、ログインした人はログインへ。 */
function sessionLost() {
  const guest = store.isGuest();
  store.clearSession();
  if (guest) {
    // 新しいゲストでも通らないなら、開き直しを繰り返さずにトップへ逃がす
    let retried = false;
    try {
      retried = sessionStorage.getItem("cos-meguri.guest-retry") === "1";
      sessionStorage.setItem("cos-meguri.guest-retry", "1");
    } catch {
      retried = true;
    }
    location.href = retried ? "/" : location.href;
    return;
  }
  location.href = `/login?expired=1&next=${encodeURIComponent(location.pathname)}`;
}

export async function api(path, { method = "GET", body, params, auth = true, retry = true } = {}) {
  const url = new URL(path, location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));

  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const token = store.token();
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));

  if (res.status === 401 && auth && token) {
    if (retry && (await refreshSession())) return api(path, { method, body, params, auth, retry: false });
    sessionLost();
    // lost: 行き先はもう決めてある。受け取った側で別の場所へ送り直さない
    throw Object.assign(new Error(t("ログインの期限が切れました。もう一度入りなおしてください。")), { lost: true });
  }
  if (!res.ok) {
    const detail = data.detail;
    const coded = ERROR_CODES[detail?.code];
    const text = coded ? t(coded, detail) : typeof detail === "string" ? detail : detail?.error || res.statusText;
    throw Object.assign(new Error(text), {
      data,
      status: res.status,
    });
  }
  if (auth && token) {
    // 通行証が通った。次に切れたときは、また1回だけ開き直してよい
    try {
      sessionStorage.removeItem("cos-meguri.guest-retry");
    } catch {
      /* 消せなくても困らない */
    }
  }
  return data;
}
