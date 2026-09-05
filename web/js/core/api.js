/* API 呼び出し。持つのは ID トークンだけで、パスワードは保持しない。 */

import * as store from "./store.js";

export async function api(path, { method = "GET", body, params, auth = true } = {}) {
  const url = new URL(path, location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));

  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const token = store.token();
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));

  if (res.status === 401 && auth) {
    store.clearSession();
    location.href = "/?expired=1";
    throw new Error("ログインの期限が切れました。もう一度入りなおしてください。");
  }
  if (!res.ok) {
    const detail = data.detail;
    throw Object.assign(new Error(typeof detail === "string" ? detail : detail?.error || res.statusText), { data });
  }
  return data;
}
