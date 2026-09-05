/* トップ。何ができるアプリかを伝えるだけの案内ページ。
   ログインはアプリ側の画面（/login）が持つ。ここには入口のボタンしか置かない。 */

import { $ } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { mountShell } from "./../core/shell.js";
import * as store from "./../core/store.js";

let layer = null;
if (store.token()) {
  try {
    layer = await api("/api/auth/session", { method: "POST", body: { handle: null } });
  } catch {
    store.clearSession();
  }
}

// トップは案内のページ。左のステップ帯は置かない
await mountShell({ authed: Boolean(layer), layer, rail: false });

// 入っている人を入口へ戻さない。続きへ送る
const cta = $("btn-start");
if (layer) {
  cta.textContent = "つづきをひらく";
  cta.href = "/prep";
}

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
