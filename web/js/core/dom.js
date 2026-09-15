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

// ---- フォームの結果の出しかた ----
//
// 出す場所は2つだけに決めてある。画面ごとに違う場所に出すと、押したあとに毎回探させる。
//   - 欄の不足や形の誤り → その欄の真下（fieldError）。欄の枠も赤くする
//   - それ以外（サーバの返事・通信の失敗・できあがりの知らせ）→ フォームの頭の1か所（formAlert）
// どちらも見えるところまで送り、欄の誤りならその欄にカーソルを置く。

/** フォームの頭に結果を1つだけ出す。HTML 側に `<div class="form-alert" hidden>` を置いておく。 */
export function formAlert(el, text, kind = "error", { html = false } = {}) {
  if (!el) return;
  el.innerHTML = `<div class="msg ${kind}">${html ? text : esc(text)}</div>`;
  el.hidden = false;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function clearFormAlert(el) {
  if (!el) return;
  el.innerHTML = "";
  el.hidden = true;
}

/** 欄の真下に、その欄の誤りを出す。 */
export function fieldError(input, text) {
  const label = input?.closest("label");
  if (!label) return;
  input.setAttribute("aria-invalid", "true");
  let note = label.querySelector(".field-error");
  if (!note) {
    note = document.createElement("p");
    note.className = "field-error";
    note.id = `${input.id}-error`;
    input.setAttribute("aria-describedby", note.id);
    label.append(note);
  }
  note.textContent = text;
}

/** 欄の誤りをまとめて消す。打ち直したら消えるように、入力のたびにも呼ぶ。 */
export function clearFieldErrors(root) {
  root.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
  root.querySelectorAll(".field-error").forEach((el) => el.remove());
}

/** 最初の誤りの欄へ送ってカーソルを置く。 */
export function focusFirstError(root) {
  const first = root.querySelector("[aria-invalid]");
  if (!first) return;
  first.scrollIntoView({ block: "center", behavior: "smooth" });
  first.focus({ preventScroll: true });
}

/** 欄を触ったら、その欄の誤りだけ消す。 */
export function clearErrorOnInput(root) {
  root.addEventListener("input", (e) => {
    const label = e.target.closest?.("label");
    if (!label) return;
    e.target.removeAttribute("aria-invalid");
    label.querySelector(".field-error")?.remove();
  });
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
