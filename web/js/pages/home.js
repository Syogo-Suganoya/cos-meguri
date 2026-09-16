/* トップ。何ができるアプリかを伝えるだけの案内ページ。
   「使ってみる」はログインせずに相談へ入る。ログインはお気に入りを使いたい人だけ。 */

import { $, esc, on } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { mountShell } from "./../core/shell.js";
import * as store from "./../core/store.js";
import { t } from "./../core/i18n.js";

let layer = null;
if (store.token()) {
  try {
    layer = await api("/api/auth/session", { method: "POST" });
  } catch {
    store.clearSession();
  }
}

// トップは案内のページ。左のステップ帯は置かない
await mountShell({ layer, rail: false });


// ---- 飛沫の層をずらして動かす ----
//
// スクロール量とポインタ位置に data-depth を掛けるだけ。奥のものほど動かない。
// 動きを減らす設定の人には何もしない（飾りなので、無くても内容は変わらない）。

const wantsMotion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
const layers = [...document.querySelectorAll(".deco [data-depth]")].map((el) => ({
  el,
  depth: Number(el.dataset.depth) || 0,
  // CSS で傾けてあるぶんは保ったまま平行移動を足す
  base: getComputedStyle(el).transform === "none" ? "" : getComputedStyle(el).transform,
}));

if (wantsMotion && layers.length) {
  let scrollY = 0;
  let pointerX = 0;
  let pointerY = 0;
  let queued = false;

  const paint = () => {
    queued = false;
    for (const { el, depth, base } of layers) {
      const y = -scrollY * depth * 0.55 + pointerY * depth * 14;
      const x = pointerX * depth * 22;
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) ${base}`;
    }
  };

  const request = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(paint);
  };

  addEventListener(
    "scroll",
    () => {
      scrollY = window.scrollY;
      request();
    },
    { passive: true }
  );

  addEventListener(
    "pointermove",
    (e) => {
      // 画面の中心を 0 として -1〜1 に均す
      pointerX = (e.clientX / innerWidth) * 2 - 1;
      pointerY = (e.clientY / innerHeight) * 2 - 1;
      request();
    },
    { passive: true }
  );

  paint();
}

// ---- 画面の写し ----
//
// 8枚を大きいまま並べるとページが伸びる。一覧は小さい画像（shots/thumbs/）で、
// 選んだ1枚だけ大きく出す。大きい画像は選ばれたときに読み込む。
// 画像は docs/shots.js が利用者と同じ順に操作して撮っている（README も同じ画像を指す）。

const SHOTS = [
  ["01-top", "トップ", "「使ってみる」はログインなしで相談へ入ります。"],
  ["02-ask", "相談", "イベント名・日付・目的地・時間と、作品名・キャラ名・出発駅・荷物。押したときに足りない欄は、その欄の真下に出ます。"],
  ["03-plan-guest", "プラン（ゲスト）", "ログインしなくてもプランは見られます。☆ を押すと、ログインと登録を案内します。"],
  ["04-signup", "アカウントを作る", "☆ の案内から来ます。ログインする前に組んだプランは、そのまま引き継ぎます。"],
  ["05-plan-makeup", "プラン: メイクの工程", "ベースからウィッグ際まで9工程。工程ごとに、なぜそうするかの根拠も添えます。"],
  ["06-plan-route", "プラン: 動線", "行きは開始までに着き、帰りは終了後に出ます。乗換ぶんの荷物の時間を足した実際の所要で出しています。"],
  ["07-me", "マイページ", "☆ で残したメイクの工程と動線。保存した時点の写しなので、組み直しても消えません。"],
  ["08-login", "ログイン", "ログインせずにマイページを開くと、ここへ送られます。入ったあとは元の画面へ戻します。"],
];

let shown = 0;

function drawThumbs() {
  $("shot-thumbs").innerHTML = SHOTS.map(
    ([file, title], i) => `
      <li>
        <button type="button" class="thumb" data-shot="${i}" aria-current="${i === shown}">
          <span class="no">${i + 1}</span>
          <img src="/static/shots/thumbs/${file}.png" alt="" loading="lazy" decoding="async">
          <span class="label">${esc(t(title))}</span>
        </button>
      </li>`
  ).join("");
}

/**
 * @param {number} index
 * @param {{ reveal?: boolean }} options `reveal: true` は選んだサムネイルを一覧内で見える位置まで送る。
 *   これは一覧そのものの中だけの移動のはずが、初回描画でも呼ぶとページ全体がここまで
 *   スクロールしてしまっていた（一覧は「使い方」よりさらに下で、開いた瞬間は画面外なので、
 *   ブラウザが「最小の移動で見せる」ためにページごと動かす）。ユーザーが選んだときだけ送る
 */
function show(index, { reveal = false } = {}) {
  shown = Math.min(SHOTS.length - 1, Math.max(0, index));
  const [file, title, detail] = SHOTS[shown];
  const image = $("shot-image");
  image.src = `/static/shots/${file}.png`;
  image.alt = t("{title}の画面", { title: t(title) });
  $("shot-title").textContent = t(title);
  $("shot-detail").textContent = t(detail);
  $("shot-counter").textContent = `${shown + 1} / ${SHOTS.length}`;
  $("shot-prev").disabled = shown === 0;
  $("shot-next").disabled = shown === SHOTS.length - 1;
  document.querySelectorAll(".thumb").forEach((b) => {
    const on = Number(b.dataset.shot) === shown;
    b.setAttribute("aria-current", String(on));
    if (on && reveal) b.scrollIntoView({ block: "nearest" });
  });
}

$("shot-thumbs").addEventListener("click", (e) => {
  const button = e.target.closest?.("button.thumb");
  if (button) show(Number(button.dataset.shot), { reveal: true });
});
on("shot-prev", "click", () => show(shown - 1, { reveal: true }));
on("shot-next", "click", () => show(shown + 1, { reveal: true }));

drawThumbs();
show(0);
