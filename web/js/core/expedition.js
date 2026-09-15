/* いま見ているプランを取り直す。

   1枚ページの頃はチャットの応答をそのまま持ち回っていたが、ページを分けると
   遷移で消える。サーバが持っている exp_id を正として引き直す。 */

import { api } from "./api.js";
import * as store from "./store.js";

/** 条件の取得は1ページ1回。相談の欄とプラン復元の両方が同じ結果を使う。 */
let pending = null;
export function chatSession() {
  if (!pending) pending = api("/api/chat");
  return pending;
}

/** いま見ているプラン。1ページ1回。枠と本文が同じ結果を使う。 */
let expPending = null;
export function currentExpedition({ refresh = false } = {}) {
  if (refresh || !expPending) expPending = loadExpedition();
  return expPending;
}

async function loadExpedition() {
  let id = store.expId();

  try {
    const chat = await chatSession();
    if (chat.exp_id) id = chat.exp_id;
  } catch {
    /* 条件が引けなくても、控えの exp_id で試す */
  }

  if (id) {
    try {
      const exp = await api(`/api/expeditions/${id}`);
      store.setExpId(id);
      return exp;
    } catch {
      store.setExpId(null); // 消えている・他人のもの
    }
  }

  const { expeditions } = await api("/api/me/expeditions");
  if (!expeditions.length) return null;
  // 一覧は順不同で返ってくるので、ここで新しい順にする
  expeditions.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  store.setExpId(expeditions[0].exp_id);
  return expeditions[0];
}
