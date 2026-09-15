/* お気に入り（メイクの工程・動線）の出し入れ。プランとマイページが使う。

   中身はサーバが本人の遠征から写すので、ここから送るのは「どのプランのどの部分か」だけ。 */

import { api } from "./api.js";

export const listFavorites = async () => (await api("/api/me/favorites")).favorites;

/** @param {{exp_id: string, kind: "makeup"|"route", direction?: "outbound"|"return"}} part */
export const addFavorite = (part) => api("/api/me/favorites", { method: "POST", body: part });

export const removeFavorite = (id) => api(`/api/me/favorites/${encodeURIComponent(id)}`, { method: "DELETE" });

/** プランのある部分が、すでに保存されているか。 */
export const findSaved = (favorites, { exp_id, kind, direction = null }) =>
  favorites.find((f) => f.exp_id === exp_id && f.kind === kind && (f.direction || null) === direction);
