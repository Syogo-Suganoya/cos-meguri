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

/* 写真の入口は2つ。カメラが使えない端末・許可しない人を締め出さないため、
   ファイル選択を必ず残す。撮った画像はサーバに送るときだけ存在し、
   ローカルには一切保存しない（<a download> も localStorage も使わない）。 */

// 送る前に縮める。長辺 720px あれば解析には足り、通信も軽い
const MAX_EDGE = 720;

/** File/Blob を、向きを保ったまま縮小して data URL にする。 */
async function toDataUrl(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", 0.85);
}

/** 解析に出す。画像はここから先へ持ち越さない。 */
async function submitFace(imageDataUrl) {
  const out = $("face-out");
  try {
    await withBusy($("btn-camera"), "解析しています…", async () => {
      const res = await api("/api/me/face", {
        method: "POST",
        body: { image_b64: imageDataUrl || null },
      });
      renderFace(res.face_profile);
      layer.face_profile = res.face_profile;
      updateRail({ layer }); // 帯の「準備」に印を入れる
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
}

// ---- ファイルを選ぶ ----

on("btn-pick", "click", () => $("face-file").click());

for (const id of ["face-file", "face-capture"]) {
  on(id, "change", async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // 同じ写真をもう一度選べるようにする
    if (!file) return;
    try {
      await submitFace(await toDataUrl(file));
    } catch {
      msg($("face-out"), "その画像は読み取れませんでした。別の写真で試してください。", "error");
    }
  });
}

// ---- カメラで撮る ----

let stream = null;

/** 使い終わったら必ず止める。止め忘れるとカメラのランプが点いたままになる。 */
function closeCamera() {
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  $("camera-panel").classList.add("hidden");
}

on("btn-camera", "click", async () => {
  // 端末にカメラが無い、または安全でない文脈（http の LAN 越しなど）では
  // getUserMedia が無い。その場合は capture 付きの入力に投げてOSに任せる
  if (!navigator.mediaDevices?.getUserMedia) {
    $("face-capture").click();
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 } },
      audio: false,
    });
  } catch {
    msg($("face-out"), "カメラを使えませんでした。「ファイルを選ぶ」から写真を渡せます。", "alert");
    return;
  }
  const view = $("camera-view");
  view.srcObject = stream;
  await view.play();
  $("camera-panel").classList.remove("hidden");
  $("btn-shoot").focus();
});

on("btn-camera-cancel", "click", closeCamera);

on("btn-shoot", "click", async () => {
  const view = $("camera-view");
  const scale = Math.min(1, MAX_EDGE / Math.max(view.videoWidth, view.videoHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(view.videoWidth * scale);
  canvas.height = Math.round(view.videoHeight * scale);
  canvas.getContext("2d").drawImage(view, 0, 0, canvas.width, canvas.height);
  closeCamera(); // 撮った直後に止める。解析を待つあいだ点けっぱなしにしない
  await submitFace(canvas.toDataURL("image/jpeg", 0.85));
});

// ページを離れるときも確実に止める
addEventListener("pagehide", closeCamera);

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


// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
renderFace(layer.face_profile);
renderFitting(await currentExpedition());
window.addEventListener("cosmeguri:expedition", (e) => renderFitting(e.detail));
