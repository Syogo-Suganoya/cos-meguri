/* ページをまたいで持ち越すもの。
   ページ分割で in-memory の state が使えなくなったので、ここに集約する。
   セッション用のキャッシュは、ページ遷移のたびに同じマスタを取り直さないため
   （会場は電波が悪い、という前提が sw.js から一貫している）。 */

const TOKEN = "cos-meguri.token";
const EXP = "cos-meguri.exp_id";
const REFRESH = "cos-meguri.refresh";
const GUEST = "cos-meguri.guest";

const local = {
  get: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k, v) => {
    try {
      v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v);
    } catch {
      /* プライベートウィンドウなど。持ち越せないだけで動作はする */
    }
  },
};

export const token = () => local.get(TOKEN);
export const refreshToken = () => local.get(REFRESH);

/** 通行証を持つ。guest はログインしていない人（Firebase の匿名ログイン）。 */
export function setTokens({ idToken, refreshToken = null, guest = false }) {
  local.set(TOKEN, idToken);
  local.set(REFRESH, refreshToken);
  local.set(GUEST, guest ? "1" : null);
}

/** 通行証だけを差し替える（更新したとき）。ゲストかどうかは変わらない。 */
export function renewTokens({ idToken, refreshToken }) {
  local.set(TOKEN, idToken);
  if (refreshToken) local.set(REFRESH, refreshToken);
}

/** 看板を通信なしで描き分けるために、ゲストかどうかも手元に控える。 */
export const isGuest = () => Boolean(token()) && local.get(GUEST) === "1";
export const isMember = () => Boolean(token()) && local.get(GUEST) !== "1";

export const expId = () => local.get(EXP);
export const setExpId = (v) => local.set(EXP, v);

export function clearSession() {
  local.set(TOKEN, null);
  local.set(REFRESH, null);
  local.set(GUEST, null);
  local.set(EXP, null);
  try {
    sessionStorage.clear();
  } catch {
    /* 消せなくても困らない */
  }
}

/** セッション中は変わらないマスタ（イベント一覧・プロバイダ・認証設定）。 */
export async function cached(key, loader) {
  try {
    const hit = sessionStorage.getItem(key);
    if (hit) return JSON.parse(hit);
  } catch {
    /* 読めなければ取り直すだけ */
  }
  const value = await loader();
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 入らなくても動く */
  }
  return value;
}
