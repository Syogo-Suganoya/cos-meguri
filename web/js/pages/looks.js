/* できあがり: 完成イメージと音声ガイド（GMI Cloud）。 */

import { $, emptyState, esc, hhmm, msg, on, withBusy } from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { mountShell, updateRail } from "./../core/shell.js";
import { focusChat, mountChat } from "./../core/chat.js";
import { currentExpedition } from "./../core/expedition.js";
import { mediaBadges } from "./../core/media.js";

const layer = await requireSession();
await mountShell({ step: "looks", layer });
mountChat();

const SECTION_LABELS = { makeup: "メイクの工程", route: "動線" };

let exp = await currentExpedition();
render(exp);
window.addEventListener("cosmeguri:expedition", (e) => {
  exp = e.detail;
  render(exp);
});

function render(current) {
  const ready = Boolean(current?.exp_id);
  document.querySelectorAll("[data-needs-plan]").forEach((el) => el.classList.toggle("hidden", !ready));

  const gate = $("looks-gate");
  if (!ready) {
    emptyState(gate, {
      text: "先にプランを組むと、完成イメージと音声ガイドを作れます。",
      action: "AIに相談する",
    });
    gate.querySelector("[data-empty-action]")?.addEventListener("click", () =>
      focusChat("9/6のコミケに横浜駅から行きます。大荷物です")
    );
    return;
  }
  gate.innerHTML = "";

  // 作ったものはリロードしても残す（作り直しを促さない）
  if (current.look_image) showLook(current.look_image);
  const guides = current.voice_guides || [];
  if (guides.length) showVoice(guides[guides.length - 1]);
}

function showLook(asset) {
  // 帯の「できあがり」に印を入れる
  if (exp) updateRail({ exp: Object.assign(exp, { look_image: asset }) });
  $("look-out").innerHTML = `
    <div class="msg">${mediaBadges(asset)}</div>
    <img class="look" src="${esc(asset.url)}" alt="完成イメージ">`;
}

function showVoice(asset, script) {
  $("voice-out").innerHTML = `
    <div class="msg">${mediaBadges(asset)} ${asset.section ? `<span class="pill">${esc(SECTION_LABELS[asset.section] || asset.section)}</span>` : ""}</div>
    <audio class="voice" controls src="${esc(asset.url)}"></audio>
    ${script ? `<div class="step"><h4>読み上げる文</h4><p>${esc(script)}</p></div>` : ""}`;
}

on("btn-look", "click", async () => {
  const out = $("look-out");
  try {
    await withBusy($("btn-look"), "つくっています…", async () => {
      const asset = await api(`/api/expeditions/${exp.exp_id}/look-image`, {
        method: "POST",
        body: { request_note: $("look-note").value },
      });
      showLook(asset);
      out.insertAdjacentHTML(
        "beforeend",
        `<div class="msg">キャラ名と作品名は画像づくりに渡していません。この画像は ${hhmm(asset.expires_at)} 頃に見られなくなります。</div>`
      );
    });
  } catch (err) {
    msg(out, err.reasons ? `${err.message}: ${err.reasons.join("、")}` : err.message, "error");
  }
});

async function speak(section, button) {
  const out = $("voice-out");
  try {
    await withBusy(button, "つくっています…", async () => {
      const res = await api(`/api/expeditions/${exp.exp_id}/voice-guide`, {
        method: "POST",
        body: { section },
      });
      showVoice({ ...res.asset, section }, res.script);
    });
  } catch (err) {
    msg(out, err.reasons ? `${err.message}: ${err.reasons.join("、")}` : err.message, "error");
  }
}

on("btn-voice-makeup", "click", (e) => speak("makeup", e.currentTarget));
on("btn-voice-route", "click", (e) => speak("route", e.currentTarget));
