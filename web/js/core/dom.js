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

/** まだ材料が揃っていない画面。何をすれば進むかを必ず書く。
 *
 * 書く場所は「相談」のページ1箇所に集めた。ここには行き先だけを置く
 * （その場に入力欄を置くと、返事の出る場所が無い）。
 */
export function emptyState(el, { text, link, note }) {
  if (!el) return;
  el.innerHTML = `
    <div class="empty">
      <p class="empty-text">${esc(text)}</p>
      ${link ? `<a class="btn primary" href="${esc(link.href)}">${esc(link.label)}</a>` : ""}
      ${note ? `<p class="empty-note">${esc(note)}</p>` : ""}
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
