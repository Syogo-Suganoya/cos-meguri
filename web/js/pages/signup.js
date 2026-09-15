/* 登録。ログインの画面から「はじめて使う」で来る。

   ログインと同じフォームにボタンを並べていた頃は、どちらを押せば登録になるのかが
   分かりにくかった。画面を分け、打ち間違いに気づけるよう確認用のパスワードを足した。 */

import { $ } from "./../core/dom.js";
import { mountShell } from "./../core/shell.js";
import { t } from "./../core/i18n.js";
import { leaveIfSignedIn, showArrivalReason, wireCredentialForm } from "./../core/credentials.js";

await leaveIfSignedIn();
await mountShell({ account: false, rail: false });

showArrivalReason();

$("to-login").href = `/login${location.search}`;

await wireCredentialForm("sign_up_url", { confirm: true, busyLabel: t("登録しています…") });
