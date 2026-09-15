/* ログイン（/login）と登録（/signup）が共有する、メール＋パスワードの受け渡し。

   ローカルも本番も Firebase Authentication に入る。ローカルは同じ REST を喋る
   エミュレータに繋がるだけで、この画面のコードは変わらない。

   誤りの出しかたは dom.js の決まりに従う。欄の誤りは欄の真下、それ以外はフォームの頭。 */

import {
  $,
  clearErrorOnInput,
  clearFieldErrors,
  clearFormAlert,
  fieldError,
  focusFirstError,
  formAlert,
  withBusy,
} from "./dom.js";
import { api } from "./api.js";
import { authConfig, firebaseToken, startSession } from "./auth.js";
import * as store from "./store.js";
import { t } from "./i18n.js";

// Identity Toolkit の返すエラーコード → 出す場所と言葉。
// field があれば欄の真下、無ければフォームの頭。知らないコードはフォームの頭にそのまま出す。
// ログインの失敗はメールとパスワードのどちらが違うかを言わない（登録の有無を漏らさないため）
const ERRORS = {
  EMAIL_NOT_FOUND: { text: t("メールアドレスかパスワードが違います。") },
  INVALID_PASSWORD: { text: t("メールアドレスかパスワードが違います。") },
  INVALID_LOGIN_CREDENTIALS: { text: t("メールアドレスかパスワードが違います。") },
  EMAIL_EXISTS: {
    field: "fb-email",
    text: t("このメールアドレスはもう登録されています。下の「ログイン」から入ってください。"),
  },
  INVALID_EMAIL: { field: "fb-email", text: t("メールアドレスの形になっていません。") },
  MISSING_PASSWORD: { field: "fb-password", text: t("パスワードを入れてください。") },
  WEAK_PASSWORD: { field: "fb-password", text: t("6文字以上にしてください。") },
  TOO_MANY_ATTEMPTS_TRY_LATER: {
    text: t("続けて失敗したので、少し時間をおいてからもう一度試してください。"),
  },
};

/** 入ったあとに戻る先。?next= があればそこ、無ければ相談。 */
export function nextPath() {
  const next = new URLSearchParams(location.search).get("next");
  return next && next.startsWith("/") ? next : "/ask";
}

/**
 * なぜここへ来たのかを、フォームの頭に1行で出す（ゲストが ☆ やマイページから来たとき）。
 * ログインと登録の画面が同じ言葉を使う。
 */
export function showArrivalReason() {
  const params = new URLSearchParams(location.search);
  const next = nextPath();
  let text = null;
  if (next.includes("fav=")) text = t("入ったあと、押した ☆ をお気に入りに保存します。");
  else if (params.get("need") === "member") text = t("マイページとお気に入りは、ログインすると使えます。");
  if (!text) return;
  // ゲストのあいだに組んだプランがあれば、引き継ぐことも添える
  if (store.isGuest()) text += t("組んだプランはそのまま引き継ぎます。");
  formAlert($("form-alert"), text, "ok");
}

/** もう入っているなら、ログインや登録の画面に留める理由がない。ゲストは留める（これから入る人）。 */
export async function leaveIfSignedIn() {
  if (!store.isMember()) return;
  try {
    await api("/api/auth/session", { method: "POST" });
    location.href = nextPath();
    await new Promise(() => {}); // 遷移するので、ここから先は動かさない
  } catch {
    store.clearSession();
  }
}

/** 押す前に分かる入力の誤りを、欄ごとに付ける。1つでもあれば true。 */
function markInputErrors({ confirm }) {
  const email = $("fb-email");
  const password = $("fb-password");
  if (!email.value.trim()) fieldError(email, t("メールアドレスを入れてください。"));
  else if (!email.validity.valid) fieldError(email, ERRORS.INVALID_EMAIL.text);

  if (!password.value) fieldError(password, ERRORS.MISSING_PASSWORD.text);
  else if (password.value.length < 6) fieldError(password, ERRORS.WEAK_PASSWORD.text);

  const again = confirm ? $("fb-password-confirm") : null;
  if (again && password.value && again.value !== password.value) {
    fieldError(again, t("上のパスワードと一致しません。"));
  }
  return Boolean($("login-form").querySelector("[aria-invalid]"));
}

/** サーバの返事や通信の失敗を、決まった場所に出す。 */
function showServerError(err, cfg) {
  const alert = $("form-alert");
  // 認証サーバに届かなかった（ローカルならエミュレータが止まっている）
  if (err instanceof TypeError) {
    return formAlert(
      alert,
      cfg.emulator
        ? t("ログインの相手（認証エミュレータ）に繋がりません。docker compose up api で起動しているか確かめてください。")
        : t("ログインの相手に繋がりません。通信の状態を確かめて、もう一度試してください。"),
    );
  }
  // "WEAK_PASSWORD : Password should be at least 6 characters" のような形で届く
  const code = String(err.message || "").split(":")[0].trim();
  const known = ERRORS[code];
  if (known?.field) {
    fieldError($(known.field), known.text);
    return focusFirstError($("login-form"));
  }
  formAlert(alert, known?.text || err.message);
}

/**
 * フォームの送信をつなぐ。
 * @param {"sign_in_url"|"sign_up_url"} urlKey どちらの REST を叩くか
 * @param {{confirm?: boolean, busyLabel: string}} options
 */
export async function wireCredentialForm(urlKey, { confirm = false, busyLabel }) {
  const cfg = await authConfig();
  const form = $("login-form");
  clearErrorOnInput(form);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFormAlert($("form-alert"));
    clearFieldErrors(form);
    if (markInputErrors({ confirm })) return focusFirstError(form);

    try {
      await withBusy($("btn-submit"), busyLabel, async () => {
        const tokens = await firebaseToken(cfg[urlKey], {
          email: $("fb-email").value.trim(),
          password: $("fb-password").value,
          apiKey: cfg.api_key,
        });
        // ゲストのあいだに組んだプランは、ここで本人へ移る
        await startSession(tokens);
        location.href = nextPath();
      });
    } catch (err) {
      showServerError(err, cfg);
    }
  });

  return cfg;
}
