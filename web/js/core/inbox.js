/* お知らせ欄。外部メッセージングは使わないので、当日の連絡はここで完結する。 */

import { $, esc, hhmm, on } from "./dom.js";
import { api } from "./api.js";

const KIND_LABELS = {
  route_delay: "動線",
  teardown: "撤収",
  awase_invite: "招待",
  reschedule_request: "返事待ち",
  reschedule_result: "変更のけっか",
  info: "お知らせ",
};

export function mountInbox() {
  document.body.insertAdjacentHTML(
    "beforeend",
    `<aside id="inbox" class="inbox hidden" aria-label="お知らせ">
       <div class="inbox-head">
         <h3>お知らせ</h3>
         <div>
           <button id="btn-read-all" class="ghost">すべて読んだ</button>
           <button id="btn-inbox-close" class="ghost">閉じる</button>
         </div>
       </div>
       <div id="inbox-list" class="inbox-list"></div>
     </aside>`
  );

  on("btn-bell", "click", () => {
    $("inbox").classList.toggle("hidden");
    refreshInbox();
  });
  on("btn-inbox-close", "click", () => $("inbox").classList.add("hidden"));
  on("btn-read-all", "click", async () => {
    await api("/api/me/notifications/read", { method: "POST", body: {} });
    refreshInbox();
  });
}

export async function refreshInbox() {
  const { notifications, unread } = await api("/api/me/notifications");
  const badge = $("bell-count");
  if (badge) {
    badge.textContent = unread;
    badge.classList.toggle("hidden", unread === 0);
  }

  const list = $("inbox-list");
  if (!list) return;
  list.innerHTML = notifications.length
    ? notifications
        .map(
          (n) => `<div class="ntf ${n.read ? "" : "unread"}">
            <div class="ntf-head"><span class="pill">${esc(KIND_LABELS[n.kind] || n.kind)}</span><span class="min">${hhmm(n.created_at)}</span></div>
            <p>${esc(n.message)}</p></div>`
        )
        .join("")
    : `<div class="msg">お知らせはまだありません。</div>`;
}
