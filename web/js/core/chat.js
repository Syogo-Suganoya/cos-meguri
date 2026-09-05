/* AIに相談するチャット。どのページにも右サイドバーとして常駐する。

   プランができたら cosmeguri:expedition を投げる。開いているページは
   その場で描き直すので、遷移もリロードもしない。 */

import { $, esc, mmdd, on } from "./dom.js";
import { api } from "./api.js";
import { eventNames } from "./shell.js";
import { refreshInbox } from "./inbox.js";
import { chatSession } from "./expedition.js";
import * as store from "./store.js";

const SLOT_LABELS = {
  event_id: "イベント",
  day: "日付",
  title: "作品名",
  character: "キャラ名",
  origin_station: "出発駅",
  luggage_mode: "荷物",
};

const LUGGAGE_LABELS = {
  light: "手荷物だけ",
  carry: "キャリー1個",
  heavy: "キャリー＋ウィッグ＋大道具",
};

const CHAT_CACHE = "cos-meguri.chat";

// 引き出しになるのは狭い画面のときだけ。広い画面では常に開いている（style.css と対）
const drawer = matchMedia("(max-width: 999px)");

/** 引き出しの開け閉め。閉じているあいだはキーボードでも入れないようにする。 */
function setOpen(open) {
  document.body.classList.toggle("chat-open", open);
  $("btn-chat-open")?.setAttribute("aria-expanded", String(open));
  const panel = $("chat");
  if (panel) panel.inert = drawer.matches && !open;
}

export function mountChat() {
  document.body.insertAdjacentHTML(
    "beforeend",
    `<button id="btn-chat-open" class="chat-fab" aria-label="AIに相談する" aria-expanded="false">AIに相談</button>
     <div id="chat-veil" class="chat-veil"></div>
     <aside id="chat" class="chat" aria-label="AIに相談">
       <div class="chat-head">
         <h2>AIに相談</h2>
         <button id="btn-chat-close" class="ghost" aria-label="閉じる">閉じる</button>
       </div>
       <p class="chat-lead">イベント・日付・作品/キャラ・出発駅・荷物がそろうと、一日ぶんを組み立てます。</p>
       <div id="chat-log" class="chat-log"></div>
       <div id="chat-slots" class="slots"></div>
       <form id="chat-form" class="chat-input">
         <input id="chat-text" placeholder="例: 9/6のコミケに横浜駅から行きます。大荷物です" autocomplete="off">
         <button class="primary" type="submit">送る</button>
         <button id="btn-chat-reset" type="button" class="ghost">はじめから</button>
       </form>
     </aside>`
  );

  on("btn-chat-open", "click", () => setOpen(!document.body.classList.contains("chat-open")));
  on("btn-chat-close", "click", () => setOpen(false));
  on("chat-veil", "click", () => setOpen(false));
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("chat-open")) setOpen(false);
  });
  // 幅が変わって引き出しでなくなったら、閉じたままにしない
  drawer.addEventListener("change", () => setOpen(false));
  setOpen(false);

  on("btn-chat-reset", "click", async () => {
    render(await api("/api/chat/reset", { method: "POST", body: {} }));
    store.setExpId(null);
  });

  on("chat-form", "submit", async (e) => {
    e.preventDefault();
    const input = $("chat-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendBubble("user", text);
    appendBubble("agent", "…", "pending");

    try {
      const session = await api("/api/chat", { method: "POST", body: { message: text } });
      render(session);
      if (session.expedition) {
        store.setExpId(session.expedition.exp_id);
        window.dispatchEvent(new CustomEvent("cosmeguri:expedition", { detail: session.expedition }));
      }
      refreshInbox();
    } catch (err) {
      document.querySelector(".bubble.pending")?.remove();
      appendBubble("agent", err.message);
    }
  });

  // 直前の会話をすぐ描いてから、サーバの内容で上書きする
  const snapshot = readCache();
  if (snapshot) render(snapshot, { cache: false });
  loadChat();
}

/** チャット欄の入力に例文を入れて、そこへ視線を送る。空状態から使う。 */
export function focusChat(example) {
  setOpen(true);
  const input = $("chat-text");
  if (!input) return;
  if (example && !input.value) input.value = example;
  input.focus();
}

async function loadChat() {
  render(await chatSession());
}

export function render(session, { cache = true } = {}) {
  const log = $("chat-log");
  if (!log) return;
  log.innerHTML = session.messages
    .map((m) => `<div class="bubble ${m.role}">${esc(m.text).replace(/\n/g, "<br>")}</div>`)
    .join("");
  log.scrollTop = log.scrollHeight;

  const slots = session.slots || {};
  $("chat-slots").innerHTML = Object.entries(SLOT_LABELS)
    .map(([key, label]) => {
      const value = slotText(key, slots[key]);
      return `<span class="slot ${value ? "on" : ""}">${esc(label)}${value ? `: ${esc(value)}` : ""}</span>`;
    })
    .join("");

  if (cache) {
    if (session.exp_id) store.setExpId(session.exp_id);
    writeCache(session);
  }
}

function appendBubble(role, text, extra = "") {
  const log = $("chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="bubble ${role} ${extra}">${esc(text)}</div>`);
  log.scrollTop = log.scrollHeight;
}

/** スロットの生値を、画面に出せる表記に直す。 */
function slotText(key, value) {
  if (value == null || value === "") return null;
  if (key === "day") return mmdd(value);
  if (key === "event_id") return eventNames[value] || value;
  if (key === "luggage_mode") return LUGGAGE_LABELS[value] || value;
  return value;
}

function readCache() {
  try {
    const hit = sessionStorage.getItem(CHAT_CACHE);
    return hit ? JSON.parse(hit) : null;
  } catch {
    return null;
  }
}

function writeCache(session) {
  try {
    sessionStorage.setItem(CHAT_CACHE, JSON.stringify({ messages: session.messages, slots: session.slots }));
  } catch {
    /* 入らなくても動く */
  }
}
