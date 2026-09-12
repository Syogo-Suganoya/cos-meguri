/* 準備: コス名を決める。

   顔の登録と試着は取り下げた。判定していた YouCam を外したので、写真を
   受け取っても返せるものが無い。入口ごと作らない——画像を一度も預からない
   ことが、いちばん強いプライバシーの担保になる。 */

import { $, emptyState, esc, msg, on, withBusy } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { mountShell, updateRail } from "./../core/shell.js";
import { currentExpedition } from "./../core/expedition.js";

const layer = await requireSession();
await mountShell({ step: "prep", layer });

// ---- コス名 ----

$("handle").value = layer.handle;

on("btn-handle", "click", async () => {
  const out = $("handle-out");
  const handle = $("handle").value.trim();
  if (!handle) return msg(out, "コス名を入れてください。", "error");
  try {
    await withBusy($("btn-handle"), "変えています…", async () => {
      const updated = await api("/api/me", { method: "PATCH", body: { handle } });
      layer.handle = updated.handle;
      // 看板の名前もその場で直す（リロードさせない）
      const who = document.querySelector(".who");
      if (who) who.textContent = updated.handle;
      msg(out, `コス名を「${updated.handle}」にしました。`, "ok");
      updateRail({ layer }); // 仮の名前から変えたら、帯の「準備」に印が入る
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
});

// ---- この先にあるもの ----

function renderNext(exp) {
  const out = $("next-out");
  if (!exp?.makeup) {
    emptyState(out, {
      text: "「相談」で条件をそろえると、一日ぶんを組み立てます。",
      link: { href: "/ask", label: "相談をひらく" },
    });
    return;
  }
  out.innerHTML = `
    <div class="msg ok">プランができています。メイクの工程と動線は<b>「プラン」</b>のページに、
      当日の進み具合と合わせは<b>「当日」</b>のページにあります。</div>
    <div class="msg">${esc(exp.event.name)}／メイク ${exp.makeup.total_minutes}分・${exp.makeup.steps.length}工程</div>`;
}

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
renderNext(await currentExpedition());
window.addEventListener("cosmeguri:expedition", (e) => renderNext(e.detail));
