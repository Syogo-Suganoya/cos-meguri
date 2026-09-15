/* ログイン。アプリ側の1画面として持つ（トップは案内だけにしてある）。

   ゲストが ☆ やマイページから来るほか、ヘッダーの「ログイン」から来る。
   入ったあとは ?next= で元のページへ戻す。はじめての人は /signup で登録する
   （同じフォームにボタンを並べると、どちらを押せばいいのか迷うため）。 */

import { $, formAlert } from "./../core/dom.js";
import { mountShell } from "./../core/shell.js";
import { t } from "./../core/i18n.js";
import { leaveIfSignedIn, showArrivalReason, wireCredentialForm } from "./../core/credentials.js";

await leaveIfSignedIn();
await mountShell({ account: false, rail: false });

showArrivalReason();

const params = new URLSearchParams(location.search);
if (params.get("expired")) {
  formAlert($("form-alert"), t("ログインの期限が切れました。もう一度入りなおしてください。"), "alert");
}

// 登録へ行くときも、戻り先は持ち越す（期限切れの印は持ち越さない）
params.delete("expired");
const query = params.toString();
$("to-signup").href = `/signup${query ? `?${query}` : ""}`;

await wireCredentialForm("sign_in_url", { busyLabel: t("確かめています…") });
