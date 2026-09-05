/* DOM まわりの小道具。 */

export const $ = (id) => document.getElementById(id);

/** 要素が無いページでは何もしない。ページごとに持つ操作が違うのでこれが既定。 */
export function on(id, event, handler) {
  const el = $(id);
  if (el) el.addEventListener(event, handler);
  return el;
}

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// 会場の時刻（JST）で表示する。訪日レイヤーが自国の端末で見ても現地時刻がずれない。
export const hhmm = (iso) =>
  iso ? new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" }) : "—";

export const mmdd = (iso) =>
  iso ? new Date(iso).toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit", timeZone: "Asia/Tokyo" }) : "—";

export function msg(el, text, kind = "") {
  if (el) el.innerHTML = `<div class="msg ${kind}">${esc(text)}</div>`;
}

/** まだ材料が揃っていない画面。何をすれば進むかを必ず書く。 */
export function emptyState(el, { text, action, skippable = false }) {
  if (!el) return;
  el.innerHTML = `
    <div class="empty">
      <p class="empty-text">${esc(text)}</p>
      ${action ? `<button class="primary" data-empty-action>${esc(action)}</button>` : ""}
      ${skippable ? `<p class="empty-note">ここは飛ばしても、ほかのページは使えます。</p>` : ""}
    </div>`;
}

export async function withBusy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await fn();
  } catch (err) {
    throw Object.assign(err, { reasons: err.data?.detail?.reasons });
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
