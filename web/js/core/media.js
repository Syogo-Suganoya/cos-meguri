/* 生成物であることを隠さずに出す。モックならその旨も添える。 */

import { esc } from "./dom.js";

export function mediaBadges(asset) {
  const badges = [`<span class="pill">${esc(asset.provider)}</span>`];
  if (asset.watermarked) badges.push(`<span class="pill ok">AIがつくった画像・音声</span>`);
  if (asset.is_placeholder) badges.push(`<span class="pill warn">見本（キー未設定）</span>`);
  return badges.join(" ");
}
