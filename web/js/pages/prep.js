/* 準備: 顔を登録する（写真はすぐ消す）と、試着の候補。 */

import { $, emptyState, esc, msg, on, withBusy } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { mountShell, updateRail } from "./../core/shell.js";
import { focusChat, mountChat } from "./../core/chat.js";
import { currentExpedition } from "./../core/expedition.js";

const layer = await requireSession();
await mountShell({ step: "prep", layer });
mountChat();

renderFace(layer.face_profile);
renderFitting(await currentExpedition());

window.addEventListener("cosmeguri:expedition", (e) => renderFitting(e.detail));

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
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
});

// ---- 顔 ----

function renderFace(profile) {
  const out = $("face-out");
  if (!profile) {
    out.innerHTML = `<div class="msg">まだ登録していません。登録すると、メイクの工程があなたの肌と顔立ちに合います。</div>`;
    return;
  }
  const attrs = Object.entries(profile.attributes)
    .filter(([k]) => !["analyzed_at", "source_image_discarded"].includes(k))
    .map(([k, v]) => `<span>${esc(k)} ${v}</span>`)
    .join("");
  out.innerHTML = `
    <div class="msg ok"><b>肌タイプ ${esc(profile.fitzpatrick_type)}</b> と顔立ちの数値だけを残しました。
      <span class="pill ok">写真は消しました</span><div class="why">${attrs}</div></div>
    <div class="msg">このあとプランを組むと、この数値でメイクの工程が変わります。</div>`;
}

on("btn-face", "click", async () => {
  // デモでは画像を送らずに登録を通す。実機ではここでカメラ入力を base64 にする
  const res = await api("/api/me/face", { method: "POST", body: {} });
  renderFace(res.face_profile);
  layer.face_profile = res.face_profile;
  updateRail({ layer }); // 帯の「準備」に印を入れる
});

// ---- 試着 ----

function renderFitting(exp) {
  const out = $("fitting-out");
  const candidates = exp?.fitting?.candidates;
  if (!candidates?.length) {
    emptyState(out, {
      text: "プランを組むと、キャラに寄せたウィッグと衣装の候補が出ます。",
      action: "AIに相談する",
      skippable: true,
    });
    out.querySelector("[data-empty-action]")?.addEventListener("click", () =>
      focusChat("9/6のコミケに横浜駅から行きます。大荷物です")
    );
    return;
  }
  out.innerHTML = `
    <div class="msg ok">試着に使った写真は消してあります。どれにするかを決めるのはあなたです（エージェントは候補を出すまで）。</div>
    <div class="cards">
      ${candidates
        .map(
          (c) => `<div class="fit"><b>${esc(c.label)}</b><br><small>${esc(c.kind)} / ${esc(c.color || "-")}</small><br>
                  <span class="pill">似あい度 ${c.fit_score}</span></div>`
        )
        .join("")}
    </div>`;
}

export { msg };
