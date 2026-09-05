/* プラン: メイクの工程・動線・更衣室。すべて組んだプランの読みもの。 */

import { $, emptyState, esc, hhmm } from "./../core/dom.js";
import { requireSession } from "./../core/auth.js";
import { mountShell } from "./../core/shell.js";
import { focusChat, mountChat } from "./../core/chat.js";
import { currentExpedition } from "./../core/expedition.js";

const layer = await requireSession();
await mountShell({ step: "plan", layer });
mountChat();

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
    $(`pane-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

function render(exp) {
  if (!exp?.makeup) {
    ["makeup", "route", "dressing"].forEach((key) => {
      const pane = $(`pane-${key}`);
      emptyState(pane, {
        text: "まだプランがありません。AIにイベント・日付・作品/キャラ・出発駅・荷物を教えてください。",
        action: "AIに相談する",
      });
      pane.querySelector("[data-empty-action]")?.addEventListener("click", () =>
        focusChat("9/6のコミケに横浜駅から行きます。大荷物です")
      );
    });
    return;
  }
  renderMakeup(exp);
  renderRoute(exp);
  renderDressing(exp);
}

/** 要約バーの1マス。数字を大きく、ラベルを小さく。 */
const fig = (value, label) => `<span class="fig"><b>${value}</b><span>${esc(label)}</span></span>`;

/** 節の頭に置く要約バー。lead には pill や chip を入れられる。 */
const summary = (figs, lead = "") => `<div class="summary">${lead}${figs.join("")}</div>`;

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
        <h4><span class="idx">${s.order}</span>${esc(s.area_label || s.area)}<span class="min">${s.minutes}分</span></h4>
        <p>${esc(s.instruction)}</p>
        ${s.personalized_for?.length ? `<div class="why">${s.personalized_for.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : ""}
      </div>`
    )
    .join("");
  $("pane-makeup").innerHTML = `
    ${summary([
      fig(`${m.steps.length}<small>工程</small>`, "ステップの数"),
      fig(`${m.total_minutes}<small>分</small>`, "ぜんぶで"),
      fig(esc(m.fitzpatrick_type), "肌タイプ"),
    ])}
    ${steps}
    ${fineprint("この工程の決めかた", m.notes)}`;
}

function renderRoute(exp) {
  $("pane-route").innerHTML = ["outbound", "return"]
    .map((dir) => {
      const r = exp.routes[dir];
      if (!r) return "";
      const legs = r.segments
        .map(
          (s) => `<div class="step"><h4>${esc(s.from_station)} → ${esc(s.to_station)}<span class="min">${s.minutes}分 / ${s.fare_yen}円</span></h4>
             <p>${esc(s.line)} ${s.has_elevator ? '<span class="pill ok">エレベーターあり</span>' : '<span class="pill warn">エレベーターなし</span>'}
             ${s.stairs ? `<span class="pill warn">階段${s.stairs}箇所</span>` : ""}</p></div>`
        )
        .join("");
      const baggage = r.effective_minutes - r.base_minutes;
      return `
      ${summary(
        [
          fig(`${hhmm(r.depart_at)} → ${hhmm(r.arrive_at)}`, "出発 → 到着"),
          fig(
            `${r.effective_minutes}<small>分</small>`,
            baggage > 0 ? `実際（ふつう ${r.base_minutes}分 ＋ 荷物 ${baggage}分）` : "実際にかかる時間"
          ),
          fig(`${Math.round(r.elevator_coverage * 100)}<small>%</small>`, "エレベーターで行ける"),
          fig(`${r.fare_yen.toLocaleString()}<small>円</small>`, `乗換 ${r.transfers}回`),
        ],
        `<span class="chip">${dir === "outbound" ? "行き" : "帰り"}</span>`
      )}
      ${legs}
      ${r.locker_suggestion ? `<div class="msg ok">${esc(r.locker_suggestion)}</div>` : ""}
      ${r.warnings.map((w) => `<div class="msg alert">${esc(w)}</div>`).join("")}`;
    })
    .join("");
}

function renderDressing(exp) {
  const d = exp.dressing;
  const max = Math.max(...d.slots.map((s) => s.occupancy), 1);
  const bars = d.slots
    .map((s) => {
      const rec = s.starts_at === d.recommended_entry || s.starts_at === d.recommended_exit;
      return `<div class="bar ${rec ? "rec" : ""}">
        <span class="time">${hhmm(s.starts_at)}</span>
        <span class="track"><span class="fill ${s.level === "peak" ? "peak" : ""}" style="width:${Math.min(100, (s.occupancy / max) * 100)}%"></span></span>
        <span class="mark">${s.wait_minutes}分待ち</span>
      </div>`;
    })
    .join("");
  $("pane-dressing").innerHTML = `
    ${summary(
      [
        fig(hhmm(d.recommended_entry), "入るのにいい時間"),
        fig(hhmm(d.recommended_exit), "出るのにいい時間"),
        fig(hhmm(d.teardown_alert_at), "片づけのお知らせ"),
      ],
      `<span class="pill warn">予測</span>`
    )}
    <div class="bars">${bars}</div>
    ${fineprint("この時間の根拠", [
      "実際に数えた数字ではなく、混みぐあいの予測です。",
      d.rationale,
    ])}`;
}

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
render(await currentExpedition());
window.addEventListener("cosmeguri:expedition", (e) => render(e.detail));
