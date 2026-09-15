/* プラン: メイクの工程と動線。すべて組んだプランの読みもの。

   メイクの工程と、動線の行き・帰りは、それぞれ ☆ でお気に入りに写せる。
   保存したものはマイページ（/me）に並び、プランを組み直しても残る。

   ログインしていない人（ゲスト）もプランは見られる。☆ はログインした人だけで、
   ゲストが押すとログインと登録を案内する。そこから入って戻ってくると
   （?fav=makeup / ?fav=route-outbound）、押した ☆ をそのまま保存する。 */

import { $, emptyState, esc, hhmm } from "./../core/dom.js";
import * as store from "./../core/store.js";
import { t } from "./../core/i18n.js";
import { requireSession } from "./../core/auth.js";
import { mountShell } from "./../core/shell.js";
import { currentExpedition } from "./../core/expedition.js";
import { addFavorite, findSaved, listFavorites, removeFavorite } from "./../core/favorites.js";

// ゲストへの案内は、通信を待たずに手元の控えで開く（あとから差し込むと本文が飛ぶ）
$("guest-promo").hidden = !store.isGuest();

const layer = await requireSession();
const guest = Boolean(layer.guest);
$("guest-promo").hidden = !guest;
await mountShell({ step: "plan", layer });

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".card > .pane").forEach((p) => p.classList.add("hidden"));
    $(`pane-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

function render(exp) {
  if (!exp?.makeup) {
    ["makeup", "route"].forEach((key) => {
      const pane = $(`pane-${key}`);
      emptyState(pane, {
        text: t("まだプランがありません。「相談」で条件をそろえると、ここに出ます。"),
        link: { href: "/ask", label: t("相談をひらく") },
      });
    });
    return;
  }
  renderMakeup(exp);
  renderRoute(exp);
}

/** 要約バーの1マス。数字を大きく、ラベルを小さく。 */
const fig = (value, label) => `<span class="fig"><b>${value}</b><span>${esc(label)}</span></span>`;

/** 節の頭に置く要約バー。lead には pill や chip、tail には ☆ ボタンを入れられる。 */
const summary = (figs, lead = "", tail = "") =>
  `<div class="summary">${lead}${figs.join("")}${tail ? `<span class="summary-tail">${tail}</span>` : ""}</div>`;

// ---- お気に入り ----

/** 保存済みのお気に入り。☆ の見た目を決めるのに使う。最初の描画の前に引く */
let favorites = [];

/** ☆ ボタン。押すと保存、もう一度押すと外す。 */
function favButton(exp, kind, direction = null) {
  const saved = findSaved(favorites, { exp_id: exp.exp_id, kind, direction });
  const what = t(kind === "makeup" ? "メイクの工程" : direction === "outbound" ? "行きの動線" : "帰りの動線");
  return `<button type="button" class="fav" aria-pressed="${Boolean(saved)}"
      data-fav-kind="${kind}" ${direction ? `data-direction="${direction}"` : ""}
      aria-label="${esc(t(saved ? "{what}をお気に入りから外す" : "{what}をお気に入りに保存", { what }))}">
      <span aria-hidden="true">${saved ? "★" : "☆"}</span>${esc(t(saved ? "保存済み" : "お気に入り"))}</button>`;
}

/** ?fav= の値。どの ☆ かを、ログインをまたいで持ち越す。 */
const favParam = (kind, direction) => (direction ? `${kind}-${direction}` : kind);

/** ☆ を押したとき。保存と取り消しを行き来する。ゲストにはログインを案内する。 */
async function toggleFavorite(button) {
  const exp = await currentExpedition();
  if (!exp) return;
  const part = { exp_id: exp.exp_id, kind: button.dataset.favKind, direction: button.dataset.direction || null };
  if (guest) return showGuestNote(part);
  const saved = findSaved(favorites, part);
  button.disabled = true;
  try {
    if (saved) {
      await removeFavorite(saved.favorite_id);
      favorites = favorites.filter((f) => f.favorite_id !== saved.favorite_id);
    } else {
      favorites = [await addFavorite(part), ...favorites];
    }
    render(exp);
    showFavNote(t(saved ? "お気に入りから外しました。" : "お気に入りに保存しました。"));
  } catch (err) {
    button.disabled = false;
    showFavNote(err.message, "error");
  }
}

/** 押した結果は、タブの上の1か所に出す（dom.js の決まりと同じく、場所を変えない）。 */
function showFavNote(text, kind = "ok") {
  const el = $("fav-note");
  el.innerHTML = `<div class="msg ${kind}">${esc(text)}${
    kind === "ok" ? ` <a href="/me">${esc(t("マイページで見る"))}</a>` : ""
  }</div>`;
  el.hidden = false;
}

/** ゲストが ☆ を押したとき。入ったらこのページへ戻り、押した ☆ を保存する。 */
function showGuestNote({ kind, direction }) {
  const next = encodeURIComponent(`/plan?fav=${favParam(kind, direction)}`);
  const el = $("fav-note");
  el.innerHTML = `<div class="msg alert">${esc(t("お気に入りはログインすると使えます。入ったあと、この ☆ をそのまま保存します。"))}
    <a href="/signup?next=${next}">${esc(t("新規登録"))}</a><a href="/login?next=${next}">${esc(t("ログイン"))}</a></div>`;
  el.hidden = false;
}

/** ログインから戻ってきたとき、押してあった ☆ を保存する。 */
async function saveCarriedFavorite(exp) {
  const params = new URLSearchParams(location.search);
  const wanted = params.get("fav");
  if (!wanted) return;
  params.delete("fav");
  history.replaceState(null, "", `${location.pathname}${params.size ? `?${params}` : ""}`);
  if (guest || !exp) return;

  const [kind, direction = null] = wanted.split("-");
  const part = { exp_id: exp.exp_id, kind, direction };
  if (findSaved(favorites, part)) return showFavNote(t("お気に入りに保存してあります。"));
  try {
    favorites = [await addFavorite(part), ...favorites];
    showFavNote(t("ログインしました。☆ を押したものをお気に入りに保存しました。"));
  } catch (err) {
    showFavNote(err.message, "error");
  }
}

document.addEventListener("click", (e) => {
  const button = e.target.closest?.("button.fav");
  if (button) toggleFavorite(button);
});

/** 方針や根拠の文。消さずに、脇の重さで末尾に置く。 */
const fineprint = (heading, lines) =>
  lines.length
    ? `<div class="fineprint"><b>${esc(heading)}</b>${lines.map((t) => `<p>${esc(t)}</p>`).join("")}</div>`
    : "";

function renderMakeup(exp) {
  const m = exp.makeup;
  const steps = m.steps
    .map(
      (s) => `
      <div class="step">
        <h4><span class="idx">${s.order}</span>${esc(s.area_label || s.area)}<span class="min">${esc(t("{n}分", { n: s.minutes }))}</span></h4>
        <p>${esc(s.instruction)}</p>
        ${s.personalized_for?.length ? `<div class="why">${s.personalized_for.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : ""}
      </div>`
    )
    .join("");
  $("pane-makeup").innerHTML = `
    ${summary([
      fig(`${m.steps.length}<small>${esc(t("工程"))}</small>`, t("ステップの数")),
      fig(`${m.total_minutes}<small>${esc(t("分"))}</small>`, t("ぜんぶで")),
    ], "", favButton(exp, "makeup"))}
    ${steps}
    ${fineprint(t("この工程の決めかた"), m.notes)}`;
}

function renderRoute(exp) {
  $("pane-route").innerHTML = ["outbound", "return"]
    .map((dir) => {
      const r = exp.routes[dir];
      if (!r) return "";
      const legs = r.segments
        .map(
          // 運賃は経路単位でしか返らない。区間に割ると2本目が「0円」に見えるので、
          // ここは所要だけ出し、運賃は上の要約バーの合計に任せる
          (s) => `<div class="step"><h4>${esc(s.from_station)} → ${esc(s.to_station)}<span class="min">${esc(t("{n}分", { n: s.minutes }))}</span></h4>
             <p>${esc(s.line)}</p></div>`
        )
        .join("");
      const baggage = r.effective_minutes - r.base_minutes;
      return `
      ${summary(
        [
          fig(`${hhmm(r.depart_at)} → ${hhmm(r.arrive_at)}`, t("出発 → 到着")),
          fig(
            `${r.effective_minutes}<small>${esc(t("分"))}</small>`,
            baggage > 0
              ? t("実際（ふつう {base}分 ＋ 荷物 {extra}分）", { base: r.base_minutes, extra: baggage })
              : t("実際にかかる時間")
          ),
          fig(`${r.transfers}<small>${esc(t("回"))}</small>`, t("乗換")),
          fig(`${r.fare_yen.toLocaleString()}<small>${esc(t("円"))}</small>`, t("運賃")),
        ],
        `<span class="chip">${esc(t(dir === "outbound" ? "行き" : "帰り"))}</span>`,
        favButton(exp, "route", dir)
      )}
      ${legs}
      ${r.warnings.map((w) => `<div class="msg alert">${esc(w)}</div>`).join("")}`;
    })
    .join("");
}

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
if (!guest) favorites = await listFavorites().catch(() => []);
const firstExp = await currentExpedition();
await saveCarriedFavorite(firstExp);
render(firstExp);
window.addEventListener("cosmeguri:expedition", (e) => render(e.detail));
