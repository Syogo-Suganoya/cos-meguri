/* マイページ: お気に入り（メイクの工程・動線）。

   相談・プランの帯は出さない。ここは保存したものを見返す場所で、順路の途中ではないため。

   お気に入りは保存した時点の写し。プランを組み直しても、ここの中身は変わらない。
   消すのは2回押し（1回目で「本当に消す」に変わる）。取り消しが効かないので、
   うっかり1回で消えないようにしている。 */

import { $, clearFormAlert, emptyState, esc, formAlert, hhmm, mmdd } from "./../core/dom.js";
import { requireMember } from "./../core/auth.js";
import { mountShell } from "./../core/shell.js";
import { listFavorites, removeFavorite } from "./../core/favorites.js";
import { t } from "./../core/i18n.js";

// お気に入りはログインした人だけ。ゲストはログインへ送られ、入ったらここへ戻る
const layer = await requireMember();
await mountShell({ layer, rail: false });

// タブが切り替えるのは一覧の枠（.fav-list）だけ。「中身を見る」の中にも .pane があるので、
// .pane で探すとそちらまで隠してしまい、切り替えのたびに中身が消えていた
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".fav-list").forEach((p) => p.classList.add("hidden"));
    $(`pane-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

// ---- お気に入り ----

let favorites = [];

const fig = (value, label) => `<span class="fig"><b>${value}</b><span>${esc(label)}</span></span>`;

function makeupBody(m) {
  return m.steps
    .map(
      (s) => `<div class="step">
        <h4><span class="idx">${s.order}</span>${esc(s.area_label || s.area)}<span class="min">${esc(t("{n}分", { n: s.minutes }))}</span></h4>
        <p>${esc(s.instruction)}</p></div>`
    )
    .join("");
}

function routeBody(r) {
  return r.segments
    .map(
      (s) => `<div class="step"><h4>${esc(s.from_station)} → ${esc(s.to_station)}<span class="min">${esc(t("{n}分", { n: s.minutes }))}</span></h4>
        <p>${esc(s.line)}</p></div>`
    )
    .join("");
}

function itemHtml(f) {
  const figs =
    f.kind === "makeup"
      ? [
          fig(`${f.makeup.steps.length}<small>${esc(t("工程"))}</small>`, t("ステップの数")),
          fig(`${f.makeup.total_minutes}<small>${esc(t("分"))}</small>`, t("ぜんぶで")),
        ]
      : [
          fig(`${hhmm(f.route.depart_at)} → ${hhmm(f.route.arrive_at)}`, t("出発 → 到着")),
          fig(`${f.route.effective_minutes}<small>${esc(t("分"))}</small>`, t("実際にかかる時間")),
          fig(`${f.route.transfers}<small>${esc(t("回"))}</small>`, t("乗換")),
          fig(`${f.route.fare_yen.toLocaleString()}<small>${esc(t("円"))}</small>`, t("運賃")),
        ];
  return `
    <article class="fav-item" data-id="${esc(f.favorite_id)}">
      <header class="fav-head">
        <h3>${esc(f.label)}</h3>
        <span class="fav-date">${esc(t("{date} に保存", { date: mmdd(f.created_at) }))}</span>
      </header>
      <div class="summary">${figs.join("")}</div>
      <details>
        <summary>${esc(t("中身を見る"))}</summary>
        <div class="pane">${f.kind === "makeup" ? makeupBody(f.makeup) : routeBody(f.route)}</div>
      </details>
      <div class="actions">
        <button type="button" class="ghost fav-delete" data-id="${esc(f.favorite_id)}">${esc(t("削除"))}</button>
      </div>
    </article>`;
}

function render() {
  for (const kind of ["makeup", "route"]) {
    const items = favorites.filter((f) => f.kind === kind);
    $(`count-${kind}`).textContent = items.length;
    const pane = $(`pane-${kind}`);
    if (!items.length) {
      emptyState(pane, {
        text:
          kind === "makeup"
            ? t("保存したメイクの工程はまだありません。プランのメイクの工程で ☆ を押すと、ここに並びます。")
            : t("保存した動線はまだありません。プランの動線で、行き・帰りそれぞれの ☆ を押すと、ここに並びます。"),
        link: { href: "/plan", label: t("プランをひらく") },
      });
      continue;
    }
    pane.innerHTML = items.map(itemHtml).join("");
  }
}

/** 削除は2回押し。1回目は確認に変えるだけで、4秒で元に戻す。 */
document.addEventListener("click", async (e) => {
  const button = e.target.closest?.("button.fav-delete");
  if (!button) return;
  if (!button.dataset.armed) {
    button.dataset.armed = "1";
    button.textContent = t("本当に消す");
    button.classList.add("danger");
    setTimeout(() => {
      if (!button.isConnected) return;
      delete button.dataset.armed;
      button.textContent = t("削除");
      button.classList.remove("danger");
    }, 4000);
    return;
  }
  button.disabled = true;
  clearFormAlert($("form-alert"));
  try {
    await removeFavorite(button.dataset.id);
    favorites = favorites.filter((f) => f.favorite_id !== button.dataset.id);
    render();
    formAlert($("form-alert"), t("お気に入りから消しました。"), "ok");
  } catch (err) {
    button.disabled = false;
    formAlert($("form-alert"), err.message);
  }
});

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
try {
  favorites = await listFavorites();
} catch (err) {
  formAlert($("form-alert"), err.message);
}
render();
