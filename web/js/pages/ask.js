/* 相談: 条件をそろえて、一日ぶんを組む。

   入口は2つあり、どちらも同じ条件（ChatSlots）に落ちる。
   ① 自由に書く → LLM が読み取る
   ② 欄を直接埋める → 読み取りを経由しない（直したとおりに入る）

   右サイドバーの常駐チャットはやめた。条件を確かめる場所と直す場所が
   別々にあると、どこを触れば結果が変わるのかが分からなくなるため。 */

import { $, esc, msg, on } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { eventNames, mountShell, updateRail } from "./../core/shell.js";
import { refreshInbox } from "./../core/inbox.js";
import { chatSession } from "./../core/expedition.js";
import * as store from "./../core/store.js";

const layer = await requireSession();
await mountShell({ step: "ask", layer });

const LUGGAGE_FALLBACK = "carry";

// 足りない項目を名前で伝えるための対応表（slot 名 → 画面の見出し）
const SLOT_LABELS = {
  event_id: "イベント",
  day: "日付",
  title: "作品名",
  character: "キャラ名",
  origin_station: "出発駅",
  luggage_mode: "荷物",
};

/** ISO文字列から JST の YYYY-MM-DD（date 入力に渡す形）。 */
function jstDate(iso) {
  return new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
}

/** 会話のやりとりを描く。 */
function renderLog(messages) {
  $("ask-log").innerHTML = (messages || [])
    .map((m) => `<div class="bubble ${m.role}">${esc(m.text).replace(/\n/g, "<br>")}</div>`)
    .join("");
  $("ask-log").scrollTop = $("ask-log").scrollHeight;
}

/** 読み取れた条件を、入力欄のほうへ反映する。 */
function renderSlots(slots) {
  const s = slots || {};
  $("slot-event").value = s.event_id || "";
  $("slot-day").value = s.day ? jstDate(s.day) : "";
  $("slot-title").value = s.title || "";
  $("slot-character").value = s.character || "";
  $("slot-station").value = s.origin_station || "";
  $("slot-luggage").value = s.luggage_mode || LUGGAGE_FALLBACK;
}

/** 足りない欄そのものに印を付ける。
 *
 * 「あと5項目」と数だけ出しても、6つ並んだどれが足りないのかは分からない。
 * 探させるより、欄の側に出す。
 */
function markMissing(missing) {
  const needed = new Set(missing || []);
  document.querySelectorAll("[data-slot]").forEach((label) => {
    label.toggleAttribute("data-needed", needed.has(label.dataset.slot));
  });
}

/** 応答をひととおり画面に流す。 */
function adopt(session) {
  renderLog(session.messages);
  renderSlots(session.slots);
  markMissing(session.missing);
  if (session.exp_id) store.setExpId(session.exp_id);
  // 帯の「相談」は条件がそろったかで点く。ここで渡さないと古いまま残る
  updateRail({ chat: session });
  if (session.expedition) {
    window.dispatchEvent(new CustomEvent("cosmeguri:expedition", { detail: session.expedition }));
    updateRail({ exp: session.expedition });
  }
  const out = $("slots-out");
  if (session.is_complete) {
    out.innerHTML = `<div class="msg ok">条件がそろいました。工程と動線は
      <a href="/plan">プラン</a> のページにあります。</div>`;
  } else {
    const names = (session.missing || []).map((k) => SLOT_LABELS[k] || k).join("・");
    out.innerHTML = `<div class="msg">あと <b>${esc(names)}</b> が要ります（${session.missing.length}項目）。
      書いても、上の欄を埋めても構いません。</div>`;
  }
  refreshInbox();
}

// ---- 書いて伝える ----

on("ask-form", "submit", async (e) => {
  e.preventDefault();
  const field = $("ask-text");
  const text = field.value.trim();
  if (!text) return;
  field.value = "";
  renderLog([...currentMessages(), { role: "user", text }, { role: "agent", text: "…" }]);
  try {
    adopt(await api("/api/chat", { method: "POST", body: { message: text } }));
  } catch (err) {
    msg($("slots-out"), err.message, "error");
  }
});

on("btn-reset", "click", async () => {
  adopt(await api("/api/chat/reset", { method: "POST", body: {} }));
  store.setExpId(null);
});

/** いま画面に出ている発言。送信中の見た目を作るのに使う。 */
function currentMessages() {
  return [...$("ask-log").querySelectorAll(".bubble")].map((el) => ({
    role: el.classList.contains("user") ? "user" : "agent",
    text: el.textContent,
  }));
}

// ---- 欄を直接埋める ----

on("btn-apply", "click", async () => {
  const day = $("slot-day").value;
  const body = {
    event_id: $("slot-event").value || null,
    // date 入力は JST の日付。会場時刻に合わせて 0 時として送る
    day: day ? new Date(`${day}T00:00:00+09:00`).toISOString() : null,
    title: $("slot-title").value.trim() || null,
    character: $("slot-character").value.trim() || null,
    origin_station: $("slot-station").value.trim() || null,
    luggage_mode: $("slot-luggage").value || null,
  };
  try {
    adopt(await api("/api/chat/slots", { method: "PATCH", body }));
  } catch (err) {
    msg($("slots-out"), err.message, "error");
  }
});

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
$("slot-event").innerHTML =
  `<option value=""></option>` +
  Object.entries(eventNames)
    .map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`)
    .join("");
adopt(await chatSession());
