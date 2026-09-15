/* 画面の言語（日英）。

   訳の鍵は日本語の原文そのもの。`t("相談")` は日本語ならそのまま、英語なら en.js の訳を返す。
   訳が無ければ原文に落ちる（画面は壊れない。漏れは tests/test_i18n.py が見張る）。

   HTML は属性で印を付け、applyI18n() がまとめて差し替える。
     data-i18n="原文"              中身の文字（子要素を持たない要素だけ）
     data-i18n-html="鍵"           中身の HTML（<b> や <br> を含む文。英語の HTML を en.js に持つ）
     data-i18n-placeholder="原文"  placeholder
     data-i18n-aria-label="原文"   aria-label

   言語は端末に控える（ログインしていなくても、トップから英語で見られるように）。
   ログインやゲストの通行証があれば、サーバにも伝えてプランの文面をその言語で組ませる。 */

import { EN } from "./en.js";

const KEY = "cos-meguri.lang";
export const LANGS = ["ja", "en"];

function readLang() {
  try {
    const v = localStorage.getItem(KEY);
    return LANGS.includes(v) ? v : null;
  } catch {
    return null;
  }
}

/** 利用者が選んだ言語。まだ選んでいなければ null。 */
export const chosenLang = readLang;

/** いまの言語。選んでいなければ日本語。 */
export const lang = () => readLang() || "ja";

export function setLang(value) {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* 控えられなくても、この画面は切り替わる */
  }
}

/** 原文を訳す。{name} は vars で埋める。 */
export function t(source, vars = {}) {
  const text = lang() === "en" ? EN[source] ?? source : source;
  return text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
}

/** 印の付いた要素をいまの言語に差し替える。日本語のときは何もしない（HTML が原文）。 */
export function applyI18n(root = document) {
  const html = document.documentElement;
  html.lang = lang();
  if (lang() !== "ja") {
    root.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    root.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const translated = EN[el.dataset.i18nHtml];
      if (translated) el.innerHTML = translated;
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
    root.querySelectorAll("[data-i18n-aria-label]").forEach((el) =>
      el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel))
    );
  }
  // 英語の人には、訳し終えるまで本文を隠している（各ページの <head> の小さな script）
  html.classList.remove("i18n-pending");
}
