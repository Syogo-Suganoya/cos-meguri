/* コスめぐり PWA。
   ログイン画面もチャット欄も自作。資格情報は Firebase Authentication に預け、
   このスクリプトが持つのは ID トークンだけ（パスワードは保持しない）。 */

const state = {
  token: null,
  layer: null,
  authConfig: null,
  exp: null,
  awaseId: null,
  lateId: null,
  proposalId: null,
  shootAt: null,
};

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "cos-meguri.token";

async function api(path, { method = "GET", body, params, auth = true } = {}) {
  const url = new URL(path, location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));

  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers["Authorization"] = `Bearer ${state.token}`;

  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && auth) {
    logout();
    throw new Error("ログインの有効期限が切れました。もう一度ログインしてください。");
  }
  if (!res.ok) {
    const detail = data.detail;
    throw Object.assign(new Error(typeof detail === "string" ? detail : detail?.error || res.statusText), { data });
  }
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// 会場の時刻（JST）で表示する。訪日レイヤーが自国の端末で見ても現地時刻がずれない。
const hhmm = (iso) =>
  iso ? new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" }) : "—";
const mmdd = (iso) =>
  iso ? new Date(iso).toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit", timeZone: "Asia/Tokyo" }) : "—";

function msg(el, text, kind = "") {
  el.innerHTML = `<div class="msg ${kind}">${esc(text)}</div>`;
}

// ---------------------------------------------------------------- 起動

async function boot() {
  state.authConfig = await api("/api/auth/config", { auth: false });
  const { events } = await api("/api/events", { auth: false });
  events.forEach((e) => (eventNames[e.event_id] = e.name));
  const providers = await api("/api/providers", { auth: false });
  $("providers").textContent = Object.entries(providers).map(([k, v]) => `${k}=${v}`).join("  ");

  if (state.authConfig.provider === "firebase") {
    $("login-firebase").classList.remove("hidden");
    $("login-dev").classList.add("hidden");
  }
  if (state.authConfig.warning) {
    const el = $("auth-warning");
    el.textContent = state.authConfig.warning;
    el.classList.remove("hidden");
  }

  const saved = localStorage.getItem(TOKEN_KEY);
  if (saved) {
    state.token = saved;
    try {
      await enterApp();
    } catch {
      logout();
    }
  }

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

async function enterApp(handle) {
  state.layer = await api("/api/auth/session", { method: "POST", body: { handle: handle || null } });
  localStorage.setItem(TOKEN_KEY, state.token);

  $("view-login").classList.add("hidden");
  $("view-app").classList.remove("hidden");
  $("btn-logout").classList.remove("hidden");
  $("btn-bell").classList.remove("hidden");

  document.querySelectorAll(".lang").forEach((b) => b.classList.toggle("active", b.dataset.lang === state.layer.lang));

  await Promise.all([loadChat(), refreshInbox()]);
}

function logout() {
  state.token = null;
  state.layer = null;
  localStorage.removeItem(TOKEN_KEY);
  $("view-app").classList.add("hidden");
  $("view-login").classList.remove("hidden");
  $("btn-logout").classList.add("hidden");
  $("btn-bell").classList.add("hidden");
  $("inbox").classList.add("hidden");
}

$("btn-logout").onclick = logout;

// ---------------------------------------------------------------- ログイン

$("btn-dev-login").onclick = async () => {
  const handle = $("dev-handle").value.trim();
  try {
    const res = await api("/api/auth/dev-login", { method: "POST", body: { handle }, auth: false });
    state.token = res.token;
    await enterApp(handle);
  } catch (err) {
    msg($("login-error"), err.message, "error");
  }
};

/** Firebase は Identity Toolkit の REST を直接叩く。SDK もCDNも使わない。 */
async function firebaseAuthRequest(url) {
  const email = $("fb-email").value.trim();
  const password = $("fb-password").value;
  const res = await fetch(`${url}?key=${encodeURIComponent(state.authConfig.api_key)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, returnSecureToken: true }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message || "ログインに失敗しました");
  return data.idToken;
}

$("btn-fb-login").onclick = async () => {
  try {
    state.token = await firebaseAuthRequest(state.authConfig.sign_in_url);
    await enterApp($("fb-handle").value.trim());
  } catch (err) {
    msg($("login-error"), err.message, "error");
  }
};

$("btn-fb-signup").onclick = async () => {
  try {
    state.token = await firebaseAuthRequest(state.authConfig.sign_up_url);
    await enterApp($("fb-handle").value.trim());
  } catch (err) {
    msg($("login-error"), err.message, "error");
  }
};

// ---------------------------------------------------------------- チャット

const SLOT_LABELS = {
  event_id: "イベント",
  day: "日付",
  title: "作品名",
  character: "キャラ名",
  origin_station: "出発駅",
  luggage_mode: "荷物",
};

const LUGGAGE_LABELS = { light: "手荷物のみ", carry: "キャリー1個", heavy: "キャリー＋ウィッグ＋大道具" };
// イベント名は API のマスタから引く（IDをそのまま出さない）
const eventNames = {};

async function loadChat() {
  renderChat(await api("/api/chat"));
}

/** スロットの生値を、画面に出せる表記に直す。 */
function slotText(key, value) {
  if (value == null || value === "") return null;
  if (key === "day") return mmdd(value);
  if (key === "event_id") return eventNames[value] || value;
  if (key === "luggage_mode") return LUGGAGE_LABELS[value] || value;
  return value;
}

$("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const input = $("chat-text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendBubble("user", text);
  appendBubble("agent", "…", "pending");

  try {
    const session = await api("/api/chat", { method: "POST", body: { message: text } });
    renderChat(session);
    if (session.expedition) {
      state.exp = session.expedition;
      renderAll(session.expedition);
      $("sec-result").classList.remove("hidden");
      $("sec-dayof").classList.remove("hidden");
      $("sec-result").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    refreshInbox();
  } catch (err) {
    document.querySelector(".bubble.pending")?.remove();
    appendBubble("agent", err.message);
  }
};

$("btn-chat-reset").onclick = async () => renderChat(await api("/api/chat/reset", { method: "POST", body: {} }));

function renderChat(session) {
  const log = $("chat-log");
  log.innerHTML = session.messages
    .map((m) => `<div class="bubble ${m.role}">${esc(m.text).replace(/\n/g, "<br>")}</div>`)
    .join("");
  log.scrollTop = log.scrollHeight;

  const slots = session.slots || {};
  $("chat-slots").innerHTML = Object.entries(SLOT_LABELS)
    .map(([key, label]) => {
      const value = slotText(key, slots[key]);
      return `<span class="slot ${value ? "on" : ""}">${esc(label)}${value ? `: ${esc(value)}` : ""}</span>`;
    })
    .join("");
}

function appendBubble(role, text, extra = "") {
  const log = $("chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="bubble ${role} ${extra}">${esc(text)}</div>`);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------- 結果表示

function renderAll(exp) {
  renderMakeup(exp);
  renderRoute(exp);
  renderDressing(exp);
  renderFitting(exp);
  renderLook(exp);
}

/** 生成済みの完成イメージがあれば復元する（作り直しを促さない）。 */
function renderLook(exp) {
  if (!exp.look_image) return;
  $("look-out").innerHTML = `
    <div class="msg">${mediaBadges(exp.look_image)}</div>
    <img class="look" src="${esc(exp.look_image.url)}" alt="完成イメージ">`;
}

function renderMakeup(exp) {
  const m = exp.makeup;
  const steps = m.steps
    .map(
      (s) => `
      <div class="step">
        <h4><span class="idx">${s.order}</span>${esc(s.area_label || s.area)}<span class="min">${s.minutes}分</span></h4>
        <p>${esc(s.instruction)}</p>
        ${s.personalized_for?.length ? `<div class="why">${s.personalized_for.map((r) => `<span>${esc(r)}</span>`).join("")}</div>` : ""}
      </div>`
    )
    .join("");
  $("pane-makeup").innerHTML = `
    <div class="msg"><b>Fitzpatrick ${esc(m.fitzpatrick_type)}</b> と顔属性で個別化した ${m.steps.length} 工程・計 ${m.total_minutes} 分。
      ${exp.extras?.wake_up_hint ? `<br>${esc(exp.extras.wake_up_hint)}` : ""}</div>
    ${m.notes.map((n) => `<div class="msg">${esc(n)}</div>`).join("")}
    ${steps}
    ${exp.extras?.cultural_note ? `<div class="msg">${esc(exp.extras.cultural_note)}</div>` : ""}`;
}

function renderRoute(exp) {
  $("pane-route").innerHTML = ["outbound", "return"]
    .map((dir) => {
      const r = exp.routes[dir];
      if (!r) return "";
      const legs = r.segments
        .map(
          (s) => `<div class="step"><h4>${esc(s.from_station)} → ${esc(s.to_station)}<span class="min">${s.minutes}分 / ${s.fare_yen}円</span></h4>
             <p>${esc(s.line)} ${s.has_elevator ? '<span class="pill ok">EVあり</span>' : '<span class="pill warn">EVなし</span>'}
             ${s.stairs ? `<span class="pill warn">階段${s.stairs}箇所</span>` : ""}</p></div>`
        )
        .join("");
      return `
      <div class="msg">
        <b>${dir === "outbound" ? "行き" : "帰り"}</b> <span class="pill">${esc(r.luggage_mode)}</span>
        <dl class="kv">
          <dt>出発</dt><dd>${hhmm(r.depart_at)}</dd>
          <dt>到着</dt><dd>${hhmm(r.arrive_at)}</dd>
          <dt>体感所要</dt><dd>${r.effective_minutes}分（素の所要 ${r.base_minutes}分 ＋ 荷物ぶん ${r.effective_minutes - r.base_minutes}分）</dd>
          <dt>EV被覆</dt><dd>${Math.round(r.elevator_coverage * 100)}%</dd>
          <dt>運賃</dt><dd>${r.fare_yen}円 / 乗換${r.transfers}回</dd>
        </dl>
      </div>
      ${legs}
      ${r.locker_suggestion ? `<div class="msg ok">${esc(r.locker_suggestion)}</div>` : ""}
      ${r.warnings.map((w) => `<div class="msg alert">${esc(w)}</div>`).join("")}`;
    })
    .join("");
}

function renderDressing(exp) {
  const d = exp.dressing;
  const max = Math.max(...d.slots.map((s) => s.occupancy), 1);
  const bars = d.slots
    .map((s) => {
      const rec = s.starts_at === d.recommended_entry || s.starts_at === d.recommended_exit;
      return `<div class="bar ${rec ? "rec" : ""}">
        <span class="time">${hhmm(s.starts_at)}</span>
        <span class="track"><span class="fill ${s.level === "peak" ? "peak" : ""}" style="width:${Math.min(100, (s.occupancy / max) * 100)}%"></span></span>
        <span class="mark">${s.wait_minutes}分待</span>
      </div>`;
    })
    .join("");
  $("pane-dressing").innerHTML = `
    <div class="msg alert"><span class="pill warn">モデル推定</span> 実測データではありません（MVPスコープ）。</div>
    <div class="msg"><dl class="kv">
      <dt>入場のおすすめ</dt><dd>${hhmm(d.recommended_entry)}</dd>
      <dt>撤収のおすすめ</dt><dd>${hhmm(d.recommended_exit)}</dd>
      <dt>撤収アラート</dt><dd>${hhmm(d.teardown_alert_at)}</dd>
    </dl></div>
    <div class="msg">${esc(d.rationale)}</div>
    <div class="bars">${bars}</div>`;
}

function renderFitting(exp) {
  const f = exp.fitting;
  if (!f?.candidates?.length) {
    $("pane-fitting").innerHTML = `<div class="msg">試着候補はありません。</div>`;
    return;
  }
  $("pane-fitting").innerHTML = `
    <div class="msg ok">試着に使った画像は破棄済みです。候補の確定はあなたが行います（エージェントは提案まで）。</div>
    <div class="cards">
      ${f.candidates
        .map((c) => `<div class="fit"><b>${esc(c.label)}</b><br><small>${esc(c.kind)} / ${esc(c.color || "-")}</small><br><span class="pill">fit ${c.fit_score}</span></div>`)
        .join("")}
    </div>`;
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
    $(`pane-${tab.dataset.tab}`).classList.remove("hidden");
  };
});

// ---------------------------------------------------------------- 生成メディア（GMI Cloud）

/** 生成物であることを隠さずに出す。モックならその旨も添える。 */
function mediaBadges(asset) {
  const badges = [`<span class="pill">${esc(asset.provider)}</span>`];
  if (asset.watermarked) badges.push(`<span class="pill ok">AI生成</span>`);
  if (asset.is_placeholder) badges.push(`<span class="pill warn">モック（キー未設定）</span>`);
  return badges.join(" ");
}

async function withBusy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await fn();
  } catch (err) {
    const reasons = err.data?.detail?.reasons;
    throw Object.assign(err, { reasons });
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

$("btn-look").onclick = async () => {
  const out = $("look-out");
  try {
    await withBusy($("btn-look"), "生成中…", async () => {
      const asset = await api(`/api/expeditions/${state.exp.exp_id}/look-image`, {
        method: "POST",
        body: { request_note: $("look-note").value },
      });
      out.innerHTML = `
        <div class="msg">${mediaBadges(asset)}</div>
        <img class="look" src="${esc(asset.url)}" alt="完成イメージ">
        <div class="msg">キャラ名・作品名は生成の入力に含めていません（設計書 §7-4）。参照は ${hhmm(asset.expires_at)} 頃に失効します。</div>`;
    });
  } catch (err) {
    const detail = err.reasons ? `${err.message}: ${err.reasons.join("、")}` : err.message;
    msg(out, detail, "error");
  }
};

async function speak(section, button) {
  const out = $("voice-out");
  try {
    await withBusy(button, "生成中…", async () => {
      const res = await api(`/api/expeditions/${state.exp.exp_id}/voice-guide`, {
        method: "POST",
        body: { section },
      });
      out.innerHTML = `
        <div class="msg">${mediaBadges(res.asset)} <span class="pill">${section === "makeup" ? "メイク工程" : "動線"}</span></div>
        <audio class="voice" controls src="${esc(res.asset.url)}"></audio>
        <div class="step"><h4>読み上げる台本</h4><p>${esc(res.script)}</p></div>`;
    });
  } catch (err) {
    const detail = err.reasons ? `${err.message}: ${err.reasons.join("、")}` : err.message;
    msg(out, detail, "error");
  }
}

$("btn-voice-makeup").onclick = (e) => speak("makeup", e.currentTarget);
$("btn-voice-route").onclick = (e) => speak("route", e.currentTarget);

$("btn-after-movie").onclick = async () => {
  const out = $("awase-out");
  try {
    await withBusy($("btn-after-movie"), "生成中…", async () => {
      // 撮影写真のアップロードはMVP外。ここではデモ用のURLを渡す
      const asset = await api(`/api/awase/${state.awaseId}/after-movie`, {
        method: "POST",
        body: {
          image_urls: ["https://example.com/shot1.jpg", "https://example.com/shot2.jpg"],
          seconds: 5,
        },
      });
      out.insertAdjacentHTML(
        "afterbegin",
        `<div class="msg ok">アフタームービーができました ${mediaBadges(asset)}</div>
         ${asset.mime_type.startsWith("video/")
            ? `<video class="look" controls src="${esc(asset.url)}"></video>`
            : `<img class="look" src="${esc(asset.url)}" alt="アフタームービー">`}`
      );
      refreshInbox();
    });
  } catch (err) {
    msg(out, err.message, "error");
  }
};

// ---------------------------------------------------------------- お知らせ

const KIND_LABELS = {
  route_delay: "動線",
  teardown: "撤収",
  awase_invite: "招待",
  reschedule_request: "承認待ち",
  reschedule_result: "リスケ結果",
  info: "お知らせ",
};

async function refreshInbox() {
  const { notifications, unread } = await api("/api/me/notifications");
  const badge = $("bell-count");
  badge.textContent = unread;
  badge.classList.toggle("hidden", unread === 0);

  $("inbox-list").innerHTML = notifications.length
    ? notifications
        .map(
          (n) => `<div class="ntf ${n.read ? "" : "unread"}">
            <div class="ntf-head"><span class="pill">${esc(KIND_LABELS[n.kind] || n.kind)}</span><span class="min">${hhmm(n.created_at)}</span></div>
            <p>${esc(n.message)}</p></div>`
        )
        .join("")
    : `<div class="msg">お知らせはまだありません。</div>`;
}

$("btn-bell").onclick = () => {
  $("inbox").classList.toggle("hidden");
  refreshInbox();
};
$("btn-inbox-close").onclick = () => $("inbox").classList.add("hidden");
$("btn-read-all").onclick = async () => {
  await api("/api/me/notifications/read", { method: "POST", body: {} });
  refreshInbox();
};

// ---------------------------------------------------------------- 顔解析

$("btn-face").onclick = async () => {
  // デモでは画像を送らずに解析を通す。実機ではここでカメラ入力を base64 にする
  const res = await api("/api/me/face", { method: "POST", body: {} });
  const p = res.face_profile;
  const attrs = Object.entries(p.attributes)
    .filter(([k]) => !["analyzed_at", "source_image_discarded"].includes(k))
    .map(([k, v]) => `<span>${esc(k)} ${v}</span>`)
    .join("");
  $("face-out").innerHTML = `
    <div class="msg ok"><b>Fitzpatrick ${esc(p.fitzpatrick_type)}</b> と顔属性スコアだけを保存しました。
      <span class="pill ok">画像は破棄済み</span><div class="why">${attrs}</div></div>
    <div class="msg">次にチャットでプランを組むと、この数値で工程が個別化されます。</div>`;
};

// ---------------------------------------------------------------- 当日モード

async function runDayOf(now) {
  const res = await api(`/api/expeditions/${state.exp.exp_id}/day-of`, { method: "POST", params: now ? { now } : undefined });
  const blocks = [];
  blocks.push(
    res.route_delay_minutes
      ? `<div class="msg alert">動線を再計算しました（+${res.route_delay_minutes}分）: ${esc(res.route_message)}</div>`
      : `<div class="msg ok">運行に乱れはありません。経路の再計算は不要でした。</div>`
  );
  if (res.dressing_alert) blocks.push(`<div class="msg alert">${esc(res.dressing_alert)}</div>`);
  if (res.proposals.length) blocks.push(`<div class="msg alert">リスケ起案 ${res.proposals.length}件（主催者の承認待ち）</div>`);
  blocks.push(`<div class="msg">お知らせ欄に ${res.notified} 件届きました。</div>`);
  $("dayof-out").innerHTML = blocks.join("");
  refreshInbox();
}

$("btn-dayof").onclick = () => runDayOf(null);
$("btn-dayof-teardown").onclick = () => {
  const at = new Date(state.exp.dressing.teardown_alert_at);
  at.setMinutes(at.getMinutes() + 5);
  return runDayOf(at.toISOString());
};

// ---------------------------------------------------------------- 合わせ

$("btn-awase").onclick = async () => {
  const day = state.exp ? new Date(state.exp.event.starts_at) : new Date(Date.now() + 7 * 864e5);
  const eventId = state.exp ? state.exp.event.event_id : "acosta";

  const awase = await api("/api/awase", {
    method: "POST",
    body: {
      title: "はじめての合わせ",
      event_id: eventId,
      day: day.toISOString(),
      members: [{ handle: "Aさん" }],
    },
  });
  state.awaseId = awase.awase_id;
  state.lateId = awase.members.find((m) => !m.is_organizer).layer_id;

  // 会場時間の13:00に撮影枠を置く
  const shootAt = new Date(day);
  shootAt.setUTCHours(4, 0, 0, 0); // 13:00 JST
  state.shootAt = shootAt;

  const withShoot = await api(`/api/awase/${state.awaseId}/shoots`, {
    method: "POST",
    body: { starts_at: shootAt.toISOString(), place: "屋上デッキ", minutes: 30 },
  });

  $("btn-late").disabled = false;
  $("btn-after-movie").disabled = false;
  renderAwase(withShoot, "合わせを作成し、13:00の撮影枠を置きました。Aさんはまだ未ログインですが、同じコス名でログインすると引き継がれます。");
  refreshInbox();
};

$("btn-late").onclick = async () => {
  const eta = new Date(state.shootAt);
  eta.setMinutes(eta.getMinutes() + 35);
  const awase = await api(`/api/awase/${state.awaseId}/progress`, {
    method: "POST",
    body: { layer_id: state.lateId, progress: "en_route", eta: eta.toISOString(), share_location: true },
  });
  $("btn-monitor").disabled = false;
  renderAwase(awase, `Aさんの到着見込みを ${hhmm(eta.toISOString())} で登録しました（位置共有は当日限定）。`);
};

$("btn-monitor").onclick = async () => {
  const now = new Date(state.shootAt);
  now.setHours(now.getHours() - 1);
  const res = await api(`/api/awase/${state.awaseId}/monitor`, { method: "POST", params: { now: now.toISOString() } });
  refreshInbox();
  if (!res.proposals.length) {
    renderAwase(res.awase, "全員が枠に間に合う見込みです。起案はありません。");
    return;
  }
  const p = res.proposals[0];
  state.proposalId = p.proposal_id;
  renderAwase(res.awase, `リスケを起案しました: ${hhmm(p.current_start)} → ${hhmm(p.proposed_start)}（+${p.delay_minutes}分）`, p);
};

const PROGRESS_LABELS = {
  invited: "招待済み",
  accepted: "参加",
  preparing: "準備中",
  en_route: "移動中",
  arrived: "到着",
  dressed: "着替え完了",
};

function renderAwase(awase, note, proposal) {
  const members = awase.members
    .map((m) => {
      const loc = m.location?.enabled
        ? `<span class="pill warn">位置共有中 ETA ${hhmm(m.location.eta)}</span>`
        : `<span class="pill">位置共有オフ</span>`;
      const progress = PROGRESS_LABELS[m.progress] || m.progress;
      return `<div class="step"><h4>${esc(m.handle)}${m.is_organizer ? "（主催者）" : ""}<span class="min">${esc(progress)}</span></h4><p>${loc}</p></div>`;
    })
    .join("");

  const shoots = awase.shoots.map((s) => `<div class="msg">撮影枠 ${hhmm(s.starts_at)} @ ${esc(s.place)}（${s.minutes}分）</div>`).join("");

  const approval = proposal
    ? `<div class="msg alert"><b>承認待ち</b>: ${esc(proposal.reason)}
         <div class="actions">
           <button onclick="decide(true)" class="primary">主催者として承認</button>
           <button onclick="decide(false)">却下</button>
         </div></div>`
    : "";

  $("awase-out").innerHTML = `
    <div class="msg ok">${esc(note)}</div>
    ${shoots}${members}
    <div class="msg">TTL: ${mmdd(awase.ttl_at)} ${hhmm(awase.ttl_at)} に位置・進捗を自動削除</div>
    ${approval}`;
}

window.decide = async (approved) => {
  const res = await api(`/api/awase/${state.awaseId}/proposals/${state.proposalId}/decision`, {
    method: "POST",
    body: { approved },
  });
  refreshInbox();
  renderAwase(
    res.awase,
    approved ? `承認しました。撮影枠を ${hhmm(res.proposal.proposed_start)} に変更しました。` : "却下しました。撮影枠は元のままです。"
  );
};

// ---------------------------------------------------------------- 監査

$("btn-audit").onclick = async () => {
  const { logs } = await api("/api/audit");
  if (!logs.length) return msg($("audit-out"), "監査ログはまだありません。");
  $("audit-out").innerHTML = logs
    .map(
      (l) => `<div class="step"><h4>${esc(l.action)}<span class="min">${hhmm(l.created_at)}</span></h4>
              <p>actor: ${esc(l.actor)} / subject: ${esc(l.subject_id || "-")}</p>
              <div class="why">${Object.entries(l.payload).map(([k, v]) => `<span>${esc(k)}: ${esc(JSON.stringify(v))}</span>`).join("")}</div></div>`
    )
    .join("");
};

$("btn-purge").onclick = async () => {
  if (!state.awaseId) return msg($("audit-out"), "先に合わせを作ってください。", "error");
  const awase = await api(`/api/awase/${state.awaseId}`);
  const after = new Date(awase.ttl_at);
  after.setHours(after.getHours() + 1);
  const res = await api("/api/tasks/purge", { method: "POST", params: { now: after.toISOString() } });
  msg($("audit-out"), `TTL削除を実行しました（対象 ${res.count} 件）。合わせの進捗・位置は履歴ごと消えています。`, "ok");
  state.awaseId = null;
};

// ---------------------------------------------------------------- 言語切替

document.querySelectorAll(".lang").forEach((btn) => {
  btn.onclick = async () => {
    document.querySelectorAll(".lang").forEach((b) => b.classList.toggle("active", b === btn));
    if (!state.token) return;
    state.layer = await api("/api/me", { method: "PATCH", body: { lang: btn.dataset.lang } });
    await api("/api/chat/reset", { method: "POST", body: {} });
    await loadChat();
  };
});

boot();
