/* 当日: 進み具合の見はりと、合わせ（みんなで撮る）。

   時計を進める・他の人になりすます、といった検証用の操作はここには置かない。
   実際の利用者が押すものだけを並べる。 */

import { $, emptyState, esc, hhmm, msg, on, withBusy } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { eventNames, mountShell, updateRail } from "./../core/shell.js";
import { focusChat, mountChat } from "./../core/chat.js";
import { currentAwase, currentExpedition } from "./../core/expedition.js";
import { refreshInbox } from "./../core/inbox.js";
import * as store from "./../core/store.js";

const layer = await requireSession();
await mountShell({ step: "day", layer });
mountChat();

const PROGRESS_LABELS = {
  invited: "招待した",
  accepted: "参加する",
  preparing: "したく中",
  en_route: "移動中",
  arrived: "着いた",
  dressed: "着替えおわり",
};

let exp = await currentExpedition();
let awase = null;
let proposalId = null;

// ---- 当日のようす ----

function renderDayOfGate() {
  const ready = Boolean(exp?.dressing);
  document.querySelectorAll("[data-needs-plan]").forEach((el) => el.classList.toggle("hidden", !ready));
  const gate = $("dayof-gate");
  if (ready) {
    gate.innerHTML = "";
    return;
  }
  emptyState(gate, {
    text: "先にプランを組むと、当日の進み具合をここで追えます。",
    action: "AIに相談する",
  });
  gate.querySelector("[data-empty-action]")?.addEventListener("click", () =>
    focusChat("9/6のコミケに横浜駅から行きます。大荷物です")
  );
}

on("btn-dayof", "click", async () => {
  const res = await api(`/api/expeditions/${exp.exp_id}/day-of`, { method: "POST" });
  const blocks = [
    res.route_delay_minutes
      ? `<div class="msg alert">電車が遅れているので、動線を計算しなおしました（+${res.route_delay_minutes}分）: ${esc(res.route_message)}</div>`
      : `<div class="msg ok">電車の乱れはありません。動線はそのままで大丈夫です。</div>`,
  ];
  if (res.dressing_alert) blocks.push(`<div class="msg alert">${esc(res.dressing_alert)}</div>`);
  if (res.proposals.length)
    blocks.push(`<div class="msg alert">時間の変更案が ${res.proposals.length}件。主催者の返事待ちです。</div>`);
  blocks.push(`<div class="msg">お知らせに ${res.notified} 件とどきました。</div>`);
  $("dayof-out").innerHTML = blocks.join("");
  refreshInbox();
});

// ---- 合わせをつくる ----

/** イベントと日は、プランがあればそこから埋める。無ければ選んでもらう。 */
function fillAwaseForm() {
  const select = $("awase-event");
  select.innerHTML = Object.entries(eventNames)
    .map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`)
    .join("");

  if (exp?.event) {
    select.value = exp.event.event_id;
    $("awase-day").value = jstDate(exp.event.starts_at);
    $("awase-title").value = `${exp.event.name} 合わせ`;
  } else {
    $("awase-day").value = jstDate(new Date(Date.now() + 7 * 864e5).toISOString());
  }
}

/** ISO文字列から JST の YYYY-MM-DD を取り出す（date 入力に渡す形）。 */
function jstDate(iso) {
  return new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
}

/** JST の日付と時刻から、絶対時刻の ISO 文字列を作る。 */
function jstMoment(date, time) {
  return new Date(`${date}T${time || "00:00"}:00+09:00`).toISOString();
}

const splitHandles = (value) =>
  value
    .split(/[,、\n]/)
    .map((s) => s.trim())
    .filter(Boolean);

on("btn-awase", "click", async () => {
  const out = $("awase-new-out");
  const title = $("awase-title").value.trim();
  const day = $("awase-day").value;
  if (!title) return msg(out, "合わせの名前を入れてください。", "error");
  if (!day) return msg(out, "日を選んでください。", "error");

  try {
    await withBusy($("btn-awase"), "つくっています…", async () => {
      const created = await api("/api/awase", {
        method: "POST",
        body: {
          title,
          event_id: $("awase-event").value,
          day: jstMoment(day, "00:00"),
          members: splitHandles($("awase-members").value).map((handle) => ({ handle })),
        },
      });
      store.setAwaseId(created.awase_id);

      const time = $("awase-time").value;
      const withShoot = time
        ? await api(`/api/awase/${created.awase_id}/shoots`, {
            method: "POST",
            body: {
              starts_at: jstMoment(day, time),
              place: $("awase-place").value.trim(),
              minutes: 30,
            },
          })
        : created;

      adoptAwase(withShoot);
      refreshInbox();
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
});

// ---- 合わせの表示と操作 ----

/** 取り直した合わせから、操作に必要な状態を導く（クリック履歴に頼らない）。 */
function adoptAwase(found) {
  awase = found;
  const has = Boolean(awase);
  $("awase-new").classList.toggle("hidden", has);
  $("awase-view").classList.toggle("hidden", !has);
  $("progress-card").classList.toggle("hidden", !has);
  updateRail(); // 帯の「当日」の印は、合わせがあるかで決まる
  if (!has) {
    fillAwaseForm();
    return;
  }

  const me = awase.members.find((m) => m.layer_id === layer.layer_id);
  // 撮影枠が無いと見はる対象が無い
  $("btn-monitor").disabled = awase.shoots.length === 0;

  if (me) {
    $("my-progress").value = me.progress === "invited" ? "accepted" : me.progress;
    $("my-share").checked = Boolean(me.location?.enabled);
    if (me.location?.eta) $("my-eta").value = hhmm(me.location.eta);
  }

  const pending = awase.proposals?.find((p) => p.status === "proposed");
  proposalId = pending?.proposal_id || null;
  renderAwase(awase, pending);
}

on("btn-progress", "click", async () => {
  const out = $("progress-out");
  const time = $("my-eta").value;
  try {
    await withBusy($("btn-progress"), "登録しています…", async () => {
      const updated = await api(`/api/awase/${awase.awase_id}/progress`, {
        method: "POST",
        body: {
          progress: $("my-progress").value,
          // 撮影と同じ日の時刻として送る
          eta: time ? jstMoment(jstDate(awase.event.starts_at), time) : null,
          share_location: $("my-share").checked,
        },
      });
      awase = updated;
      renderAwase(updated, updated.proposals?.find((p) => p.status === "proposed"));
      msg(out, "登録しました。", "ok");
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
});

on("btn-monitor", "click", async () => {
  const res = await api(`/api/awase/${awase.awase_id}/monitor`, { method: "POST" });
  awase = res.awase;
  refreshInbox();
  if (!res.proposals.length) {
    renderAwase(res.awase, null, "全員まにあう見込みです。変更の案はありません。");
    return;
  }
  const p = res.proposals[0];
  proposalId = p.proposal_id;
  renderAwase(res.awase, p, `撮影の時間をずらす案を出しました: ${hhmm(p.current_start)} → ${hhmm(p.proposed_start)}（+${p.delay_minutes}分）`);
});

function renderAwase(current, proposal, note = "") {
  const members = current.members
    .map((m) => {
      const loc = m.location?.enabled
        ? `<span class="pill warn">位置を共有中${m.location.eta ? `・${hhmm(m.location.eta)}着の見込み` : ""}</span>`
        : `<span class="pill">位置は共有していません</span>`;
      const progress = PROGRESS_LABELS[m.progress] || m.progress;
      return `<div class="step"><h4>${esc(m.handle)}${m.is_organizer ? "（主催者）" : ""}${m.layer_id === layer.layer_id ? "・じぶん" : ""}<span class="min">${esc(progress)}</span></h4><p>${loc}</p></div>`;
    })
    .join("");

  const shoots = current.shoots.length
    ? current.shoots
        .map((s) => `<div class="msg">撮影 ${hhmm(s.starts_at)} ＠ ${esc(s.place || "場所は未定")}（${s.minutes}分）</div>`)
        .join("")
    : `<div class="msg">撮影の枠はまだありません。</div>`;

  const approval = proposal
    ? `<div class="msg alert"><b>返事待ち</b>: ${esc(proposal.reason)}
         <div class="actions">
           <button class="primary" data-decide="yes">主催者としてOKする</button>
           <button data-decide="no">やめておく</button>
         </div></div>`
    : "";

  $("awase-out").innerHTML = `
    ${note ? `<div class="msg ok">${esc(note)}</div>` : ""}
    <div class="msg"><b>${esc(current.title)}</b>／${esc(current.event.name)}</div>
    ${shoots}${members}
    ${approval}`;
}

// 承認・却下はイベント委譲で受ける（モジュールの中の関数は onclick 属性から呼べない）
on("awase-out", "click", async (e) => {
  const button = e.target.closest("[data-decide]");
  if (!button || !proposalId) return;
  const approved = button.dataset.decide === "yes";
  const res = await api(`/api/awase/${awase.awase_id}/proposals/${proposalId}/decision`, {
    method: "POST",
    body: { approved },
  });
  awase = res.awase;
  proposalId = null;
  refreshInbox();
  renderAwase(
    res.awase,
    null,
    approved
      ? `OKしました。撮影を ${hhmm(res.proposal.proposed_start)} に変えました。`
      : "やめておきました。撮影の時間はそのままです。"
  );
});

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
renderDayOfGate();
adoptAwase(await currentAwase());

window.addEventListener("cosmeguri:expedition", (e) => {
  exp = e.detail;
  renderDayOfGate();
  if (!awase) fillAwaseForm();
});
