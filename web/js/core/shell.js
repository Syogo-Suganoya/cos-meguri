/* 全ページ共通の枠（看板・ステップの帯・お知らせ・脚注）を組み立てる。
   HTML を6枚に複製するとズレるので、枠はここが唯一の出どころ。 */

import { $, esc, hhmm, on } from "./dom.js";
import { api } from "./api.js";
import { logout } from "./auth.js";
import { chatSession, currentExpedition } from "./expedition.js";
import * as store from "./store.js";
import { mountInbox, refreshInbox } from "./inbox.js";

// 左端のシェブロン。並びに順番はあるが、順路ではない。どの節から始めてもよく、
// 飛ばしても構わない。番号は「何番目にやること」ではなく、できたら ✓ に変わる目印。
export const STEPS = [
  // 相談は「条件がそろったか」。プランと同じ条件にすると2節が常に同時に点く
  { key: "ask", href: "/ask", label: "相談", done: ({ chat }) => Boolean(chat?.is_complete) },
  {
    key: "prep",
    href: "/prep",
    label: "準備",
    // 端末につけた仮の名前から変えたら「決めた」とみなす
    done: ({ layer }) => Boolean(layer?.handle) && layer.handle !== store.loginHandle(),
  },
  { key: "plan", href: "/plan", label: "プラン", done: ({ exp }) => Boolean(exp?.makeup) },
  { key: "day", href: "/day", label: "当日", done: () => Boolean(store.awaseId()) },
];

export const eventNames = {};

function railHtml(current) {
  return STEPS.map(
    (s, i) => `
    <a class="rail-step" href="${s.href}" data-step="${s.key}"
       ${s.key === current ? 'aria-current="page"' : ""}>
      <span class="n">${i + 1}</span><span class="t">${esc(s.label)}</span>
    </a>`
  ).join("");
}

// 帯が見ている材料。ページ側で何かが増えたら updateRail() で知らせる
const railState = { layer: null, exp: null, chat: null };

/** 節ごとに、材料がそろっているかを目印に出す。番号は「まだ」の印として残す。 */
export function updateRail(patch = {}) {
  Object.assign(railState, patch);
  paintRail(railState);
}

function paintRail(state) {
  for (const step of STEPS) {
    const el = document.querySelector(`.rail-step[data-step="${step.key}"]`);
    if (!el) continue;
    const done = step.done(state);
    el.toggleAttribute("data-done", done);
    el.querySelector(".n").textContent = done ? "✓" : String(STEPS.indexOf(step) + 1);
    el.setAttribute("aria-label", `${step.label}${done ? "（できています）" : ""}`);
  }
}

function headerHtml(authed, layer) {
  return `
    <a class="brand" href="/">
      <span class="mark" aria-hidden="true">◈</span>
      <span class="brand-name">コスめぐり</span>
    </a>
    <div class="top-right">
      <div class="lang-switch">
        <button class="lang" data-lang="ja">日本語</button>
        <button class="lang" data-lang="en">English</button>
      </div>
      ${
        authed
          ? `<button id="btn-bell" class="bell" title="お知らせ" aria-label="お知らせ">
               <span aria-hidden="true">🔔</span><span id="bell-count" class="badge hidden">0</span>
             </button>
             <span class="who">${esc(layer?.handle || "")}</span>
             <button id="btn-logout" class="ghost">ログアウト</button>`
          : ""
      }
    </div>`;
}

/**
 * 枠を差し込む。
 * @param {{step?: string, authed?: boolean, layer?: object}} options
 */
export async function mountShell({ step = null, authed = true, layer = null, rail = true } = {}) {
  const withRail = authed && rail;
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<header class="top">${headerHtml(authed, layer)}</header>
     ${withRail ? `<nav class="rail" aria-label="進みぐあい">${railHtml(step)}</nav>` : ""}`
  );

  document.body.insertAdjacentHTML(
    "beforeend",
    `<footer>
       <p>顔写真は受け取りません。位置の共有はイベントの当日だけで、終わって24時間で無効になります。</p>
     </footer>`
  );

  if (authed) {
    mountInbox();
    on("btn-logout", "click", logout);
    // 狭い画面では帯が横スクロールになる。いまいる節を見えるところへ送る
    document
      .querySelector(".rail-step[aria-current]")
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  }

  // イベント名のマスタはセッション中に変わらない。ページを移るたびに取り直さない
  const { events } = await store.cached("cos-meguri.events", () =>
    api("/api/events", { auth: false })
  );
  events.forEach((e) => (eventNames[e.event_id] = e.name));

  const lang = layer?.lang || "ja";
  document.querySelectorAll(".lang").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === lang);
    b.addEventListener("click", async () => {
      document.querySelectorAll(".lang").forEach((x) => x.classList.toggle("active", x === b));
      if (!store.token()) return;
      await api("/api/me", { method: "PATCH", body: { lang: b.dataset.lang } });
      await api("/api/chat/reset", { method: "POST", body: {} });
      location.reload();
    });
  });

  if (authed) refreshInbox();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

  // 目印はプランを引けてから。枠の描画はここで待たせない
  if (withRail) {
    updateRail({ layer, exp: null, chat: null });
    currentExpedition()
      .then((exp) => updateRail({ exp }))
      .catch(() => {});
    chatSession()
      .then((chat) => updateRail({ chat }))
      .catch(() => {});
    window.addEventListener("cosmeguri:expedition", (e) => updateRail({ exp: e.detail }));
  }
}

export { hhmm };
