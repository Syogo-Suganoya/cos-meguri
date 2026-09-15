/* 全ページ共通の枠（看板・ステップの帯）を組み立てる。
   HTML をページごとに複製するとズレるので、枠はここが唯一の出どころ。 */

import { $, esc, hhmm, on } from "./dom.js";
import { api } from "./api.js";
import { logout } from "./auth.js";
import { chatSession, currentExpedition } from "./expedition.js";
import * as store from "./store.js";
import { applyI18n, chosenLang, lang, setLang, t } from "./i18n.js";

// 左端のシェブロン。並びに順番はあるが、順路ではない。どの節から始めてもよく、
// 飛ばしても構わない。番号は「何番目にやること」ではなく、できたら ✓ に変わる目印。
export const STEPS = [
  // 相談は「条件がそろったか」。プランと同じ条件にすると2節が常に同時に点く
  { key: "ask", href: "/ask", label: "相談", done: ({ chat }) => Boolean(chat?.is_complete) },
  { key: "plan", href: "/plan", label: "プラン", done: ({ exp }) => Boolean(exp?.makeup) },
];

export const eventNames = {};
// 収載イベントごとの、相談の欄に自動で入れる目的地と時刻
export const eventDefaults = {};

function railHtml(current) {
  return STEPS.map(
    (s, i) => `
    <a class="rail-step" href="${s.href}" data-step="${s.key}"
       ${s.key === current ? 'aria-current="page"' : ""}>
      <span class="n">${i + 1}</span><span class="t">${esc(t(s.label))}</span>
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
    el.setAttribute("aria-label", `${t(step.label)}${done ? t("（できています）") : ""}`);
  }
}

/**
 * 看板の右端。ログインした人はマイページとログアウト、それ以外（ゲスト）はログインと登録。
 * ゲストに常に見せておくのが、お気に入りへのいちばん静かな案内になる。
 */
function accountHtml(member) {
  if (member) {
    return `<a class="top-link" href="/me"${location.pathname === "/me" ? ' aria-current="page"' : ""}>${t("マイページ")}</a>
    <button id="btn-logout" class="ghost">${t("ログアウト")}</button>`;
  }
  // 入ったあとは、いま見ているページへ戻す（トップからなら相談へ）
  const next = location.pathname === "/" ? "" : `?next=${encodeURIComponent(location.pathname)}`;
  return `<a class="top-link" href="/login${next}">${t("ログイン")}</a>
    <a class="btn top-signup" href="/signup${next}">${t("新規登録")}</a>`;
}

function headerHtml(account) {
  return `
    <a class="brand" href="/">
      <span class="mark" aria-hidden="true">◈</span>
      <span class="brand-name">${t("コスめぐり")}</span>
    </a>
    <div class="top-right">
      <div class="lang-switch">
        <!-- 狭い画面では短い表記に切り替える（ロゴの文字を消さずに看板へ収めるため） -->
        <button class="lang" data-lang="ja" aria-label="日本語"><span class="lang-long">日本語</span><span class="lang-short">JA</span></button>
        <button class="lang" data-lang="en" aria-label="English"><span class="lang-long">English</span><span class="lang-short">EN</span></button>
      </div>
      <span class="top-account">${account ? accountHtml(store.isMember()) : ""}</span>
    </div>`;
}

/**
 * 枠の骨組みを、通信を待たずにすぐ描く。このモジュールを読み込んだ瞬間に動く。
 *
 * 以前はログインの確認（通信）を待ってから看板と帯を差し込んでいたので、
 * 最初の一瞬は本文が左上に詰まって描かれ、差し込んだ瞬間に下と右へ飛んでいた。
 * いまは各ページの HTML に空の `<header class="top">` と `<nav class="rail">` を
 * 置いて場所を先に確保し、ここで中身を埋める。
 *   - `data-authed` があれば、看板の右端（ログイン済みならマイページとログアウト、
 *     ゲストならログインと新規登録）も最初から出す。どちらかは手元の控え（store）で決める
 *   - `nav.rail[data-step]` がいまいる節
 */
function drawFrame() {
  const header = document.querySelector("header.top");
  if (header && !header.childElementCount) header.innerHTML = headerHtml(header.hasAttribute("data-authed"));
  const nav = document.querySelector("nav.rail");
  if (nav && !nav.childElementCount) nav.innerHTML = railHtml(nav.dataset.step);
}
// 訳してから枠を描く。どちらも通信を待たない
applyI18n();
drawFrame();

/**
 * 枠を仕上げる（ログアウト・言語・帯の目印をつなぐ）。骨組みは drawFrame が描いてある。
 * @param {{step?: string, account?: boolean, layer?: object, rail?: boolean}} options
 *   account: 看板の右端を出すか（ログインと登録の画面は出さない）
 */
export async function mountShell({ step = null, account = true, layer = null, rail = true } = {}) {
  const withRail = rail;
  // サーバの答えがあればそれを正とする（手元の控えが古いこともある）
  const member = layer ? !layer.guest : store.isMember();

  // 置き場所が無いページでも動くように、無ければ差し込む
  if (!document.querySelector("header.top")) {
    document.body.insertAdjacentHTML("afterbegin", `<header class="top">${headerHtml(account)}</header>`);
  }
  const slot = document.querySelector(".top-account");
  const drawn = !slot?.childElementCount ? null : Boolean(slot.querySelector("#btn-logout"));
  if (slot && (account ? drawn !== member : drawn !== null)) slot.innerHTML = account ? accountHtml(member) : "";

  const nav = document.querySelector("nav.rail");
  if (withRail && !nav) {
    document.querySelector("header.top").insertAdjacentHTML(
      "afterend",
      `<nav class="rail" aria-label="${t("進みぐあい")}">${railHtml(step)}</nav>`
    );
  } else if (!withRail && nav) {
    nav.remove();
  }

  if (account && member) on("btn-logout", "click", logout);
  if (withRail) {
    // 狭い画面では帯が横スクロールになる。いまいる節を見えるところへ送る
    document
      .querySelector(".rail-step[aria-current]")
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  }

  // イベント名のマスタはセッション中に変わらない。ページを移るたびに取り直さない
  // キーの末尾は形の版。defaults を足したとき、古い形の控えを読まないように上げた
  const { events } = await store.cached("cos-meguri.events.v2", () =>
    api("/api/events", { auth: false })
  );
  events.forEach((e) => {
    eventNames[e.event_id] = lang() === "en" ? e.name_en : e.name;
    eventDefaults[e.event_id] = e.defaults;
  });

  // 画面の言語は端末の控えが正。サーバ（プランの文面の言語）と食い違っていたら合わせる
  if (layer && layer.lang !== lang()) {
    if (chosenLang()) {
      // この端末で選んだ言語をサーバに伝える。組み上がったプランはその言語で組み直される
      await api("/api/me", { method: "PATCH", body: { lang: lang() } }).catch(() => {});
    } else {
      // まだ選んでいない端末では、アカウントの言語に合わせて開き直す
      setLang(layer.lang);
      location.reload();
      await new Promise(() => {});
    }
  }

  document.querySelectorAll(".lang").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === lang());
    b.addEventListener("click", async () => {
      if (b.dataset.lang === lang()) return;
      document.querySelectorAll(".lang").forEach((x) => {
        x.classList.toggle("active", x === b);
        x.disabled = true; // プランを組み直すあいだに二度押しさせない
      });
      setLang(b.dataset.lang);
      if (store.token()) {
        await api("/api/me", { method: "PATCH", body: { lang: b.dataset.lang } }).catch(() => {});
      }
      location.reload();
    });
  });

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
