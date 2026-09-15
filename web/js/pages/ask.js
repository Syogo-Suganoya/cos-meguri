/* 相談: 欄で条件をそろえて、一日ぶんを組む。

   イベントは名前・目的地（最寄り駅）・開始・終了で表す。収載イベントの名前なら
   目的地と時刻を自動で埋める（書き換えてよい）。ローカルイベントなど収載に無いものは、
   3つを自分で入れれば組める。

   自由に書いて伝える入口は取り下げた。欄を埋めれば読み違いが起きないので、
   読み取った結果を確かめて直す、という往復そのものが要らない。

   組み上がったらプランのページへ移る。ここに「できました」とだけ出して
   留めると、押したのに何も起きなかったように見える。

   誤りの出しかたは dom.js の決まりに従う。足りない欄は欄の真下、それ以外はフォームの頭。 */

import {
  $,
  clearErrorOnInput,
  clearFieldErrors,
  clearFormAlert,
  esc,
  fieldError,
  focusFirstError,
  formAlert,
  on,
  withBusy,
} from "./../core/dom.js";
import { api } from "./../core/api.js";
import { requireSession } from "./../core/auth.js";
import { eventDefaults, eventNames, mountShell, updateRail } from "./../core/shell.js";
import { chatSession } from "./../core/expedition.js";
import * as store from "./../core/store.js";
import { t } from "./../core/i18n.js";

const layer = await requireSession();
await mountShell({ step: "ask", layer });

const LUGGAGE_FALLBACK = "carry";

// slot 名 → 欄と、足りないときに出す言葉
const SLOTS = {
  event_name: { input: "slot-event", missing: t("イベント名を入れてください。") },
  day: { input: "slot-day", missing: t("日付を入れてください。") },
  destination_station: { input: "slot-destination", missing: t("目的地の最寄り駅を入れてください。") },
  starts_time: { input: "slot-starts", missing: t("開始の時刻を入れてください。") },
  ends_time: { input: "slot-ends", missing: t("終了の時刻を入れてください。") },
  title: { input: "slot-title", missing: t("作品名を入れてください。") },
  character: { input: "slot-character", missing: t("キャラ名を入れてください。") },
  origin_station: { input: "slot-station", missing: t("出発駅を入れてください。") },
  luggage_mode: { input: "slot-luggage", missing: t("荷物を選んでください。") },
};

// 収載イベントの名前で自動に埋める欄。data-auto は「自動で入れた値」の印で、手で打つと外れる
const AUTO_FIELDS = ["slot-destination", "slot-starts", "slot-ends"];

/**
 * イベント名が収載イベントに当たったら、目的地と時刻を埋める。
 * 空の欄と、前に自動で入れた欄だけを書き換える。手で直した欄は触らない。
 */
async function autofillEvent() {
  const name = $("slot-event").value.trim();
  if (!name) return;
  let event = null;
  try {
    ({ event } = await api("/api/events/match", { params: { name }, auth: false }));
  } catch {
    return; // 埋められなくても、手で入れれば組める
  }
  if (!event || $("slot-event").value.trim() !== name) return;
  const values = {
    "slot-destination": event.defaults.destination_station,
    "slot-starts": event.defaults.starts_time,
    "slot-ends": event.defaults.ends_time,
  };
  for (const [id, value] of Object.entries(values)) {
    const input = $(id);
    if (input.value && !input.dataset.auto) continue;
    input.value = value;
    input.dataset.auto = "1";
    clearFieldErrors(input.closest("label"));
  }
}

/**
 * 駅名の欄に、正式な駅名の候補を出す。「大宮」は埼玉と京都にあり、そのままでは経路が引けない。
 * 打つたびに駅すぱあとを呼ばないよう、手が止まってから聞く。
 */
function wireStationOptions(inputId, listId) {
  const input = $(inputId);
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const name = input.value.trim();
    if (!name) return;
    timer = setTimeout(async () => {
      try {
        const { stations } = await api("/api/stations", { params: { name } });
        if (input.value.trim() !== name) return; // 聞いているあいだに書き換わった
        $(listId).innerHTML = stations.map((s) => `<option value="${esc(s)}"></option>`).join("");
      } catch {
        /* 候補が出ないだけで、手で入れれば組める */
      }
    }, 350);
  });
}

/** ISO文字列から JST の YYYY-MM-DD（date 入力に渡す形）。 */
function jstDate(iso) {
  return new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
}

/** 保存されている条件を欄に戻す。 */
function renderSlots(slots) {
  const s = slots || {};
  $("slot-event").value = s.event_name || "";
  $("slot-day").value = s.day ? jstDate(s.day) : "";
  $("slot-destination").value = s.destination_station || "";
  $("slot-starts").value = s.starts_time || "";
  $("slot-ends").value = s.ends_time || "";
  // マスタと同じ値なら自動で入った値として扱う（別の収載イベントに変えたら入れ替わる）。
  // 違う値は利用者が直したものなので、イベント名を変えても上書きしない
  const defaults = eventDefaults[s.event_id] || {};
  const keys = { "slot-destination": "destination_station", "slot-starts": "starts_time", "slot-ends": "ends_time" };
  for (const [id, key] of Object.entries(keys)) {
    if ($(id).value && $(id).value === defaults[key]) $(id).dataset.auto = "1";
    else delete $(id).dataset.auto;
  }
  $("slot-title").value = s.title || "";
  $("slot-character").value = s.character || "";
  $("slot-station").value = s.origin_station || "";
  $("slot-luggage").value = s.luggage_mode || LUGGAGE_FALLBACK;
}

/** 足りない欄の真下に、何を入れればいいかを出す。押したあとだけ出す。
 *
 * 開いた直後から6つ全部に印を付けると、まだ何もしていないのに叱られているように見える。
 */
function markMissing(missing) {
  const form = $("slots-form");
  clearFieldErrors(form);
  (missing || []).forEach((key) => {
    const slot = SLOTS[key];
    if (slot) fieldError($(slot.input), slot.missing);
  });
  focusFirstError(form);
}

/** 応答を画面に流す。組み上がっていれば true。 */
function adopt(session, { submitted = false } = {}) {
  renderSlots(session.slots);
  if (session.exp_id) store.setExpId(session.exp_id);
  // 帯の「相談」は条件がそろったかで点く。ここで渡さないと古いまま残る
  updateRail({ chat: session });
  if (session.expedition) updateRail({ exp: session.expedition });

  if (session.is_complete) {
    formAlert($("form-alert"), `${esc(t("この条件でプランができています。"))}<a href="/plan">${esc(t("プランを見る"))}</a>`, "ok", {
      html: true,
    });
    return true;
  }
  if (submitted) markMissing(session.missing);
  return false;
}

on("btn-apply", "click", async () => {
  clearFormAlert($("form-alert"));
  clearFieldErrors($("slots-form"));
  const day = $("slot-day").value;
  const body = {
    // イベントは名前で送る。サーバが収載イベントに引き当てる
    event_name: $("slot-event").value.trim(),
    // 空のまま送ると、収載イベントならサーバがマスタで埋める
    destination_station: $("slot-destination").value.trim(),
    starts_time: $("slot-starts").value,
    ends_time: $("slot-ends").value,
    // date 入力は JST の日付。会場時刻に合わせて 0 時として送る
    day: day ? new Date(`${day}T00:00:00+09:00`).toISOString() : null,
    title: $("slot-title").value.trim() || null,
    character: $("slot-character").value.trim() || null,
    origin_station: $("slot-station").value.trim() || null,
    luggage_mode: $("slot-luggage").value || null,
  };
  try {
    await withBusy($("btn-apply"), t("組み立てています…"), async () => {
      const session = await api("/api/chat/slots", { method: "PATCH", body });
      if (adopt(session, { submitted: true }) && session.expedition) location.href = "/plan";
    });
  } catch (err) {
    // 欄の誤り（終了が開始より前など）は、その欄の真下に出す
    const slot = SLOTS[err.data?.detail?.field];
    if (slot) {
      fieldError($(slot.input), err.message);
      focusFirstError($("slots-form"));
    } else {
      formAlert($("form-alert"), err.message);
    }
  }
});

// 最初の描画はここ。const の宣言より前に呼ぶと、参照した瞬間に例外で止まる
$("event-options").innerHTML = Object.values(eventNames)
  .map((name) => `<option value="${esc(name)}"></option>`)
  .join("");
clearErrorOnInput($("slots-form"));
$("slot-event").addEventListener("change", autofillEvent);
wireStationOptions("slot-destination", "destination-options");
wireStationOptions("slot-station", "station-options");
AUTO_FIELDS.forEach((id) => $(id).addEventListener("input", (e) => delete e.target.dataset.auto));
adopt(await chatSession());
