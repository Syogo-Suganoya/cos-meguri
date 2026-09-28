/**
 * 提出用のデモ動画を撮る。
 *
 *   docker compose up -d api
 *   docker compose --profile shots run --rm demo
 *
 * shots.js と同じ流れ（ゲストで相談 → プラン → ☆ から登録 → マイページ）を、人が操作しているように
 * ゆっくり動かして録画する。トップ（案内のページ）は撮らず、相談から始める。
 * ヘッドレスのブラウザにはマウスの矢印が出ないので、ページに矢印を差し込んで見せている。
 *
 * プランを組み立てている待ち時間（Gemini と駅すぱあとを呼ぶ）は、書き出すときに早送りする。
 *
 * 出力: docs/demo/cos-meguri-demo.mp4（録画の webm を H.264 に変換したもの。docs/demo/ は git に入れない）
 */

const fs = require("fs");
const { execFileSync } = require("child_process");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE_URL || "http://api:8080";
const OUT = process.env.OUT_DIR || "/work/docs/demo";
const AUTH_PUBLIC = process.env.AUTH_PUBLIC || "http://localhost:9099";
const AUTH_INTERNAL = process.env.AUTH_INTERNAL || "http://firebase-auth:9099";
// プランの組み立てを待つあいだを何倍で流すか
const WAIT_SPEED = 8;
const WIDTH = 1280;
const HEIGHT = 800;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`${BASE}/health`);
      if (res.ok) return;
    } catch {
      /* まだ起動していない */
    }
    await sleep(1000);
  }
  throw new Error(`${BASE} が起動しなかった。先に docker compose up -d api を実行する`);
}

/** ページごとに差し込む、マウスの矢印とクリックの波紋。 */
function installCursor() {
  const draw = () => {
    if (document.getElementById("__demo-cursor")) return;
    const style = document.createElement("style");
    style.textContent = `
      #__demo-cursor { position: fixed; left: 0; top: 0; width: 22px; height: 22px; z-index: 2147483647;
        pointer-events: none; transform: translate(-100px, -100px); }
      #__demo-cursor svg { display: block; filter: drop-shadow(0 1px 2px rgba(0,0,0,.4)); }
      .__demo-ripple { position: fixed; width: 36px; height: 36px; margin: -18px 0 0 -18px; border-radius: 50%;
        border: 3px solid rgba(255, 90, 140, .9); z-index: 2147483646; pointer-events: none;
        animation: __demo-ripple .5s ease-out forwards; }
      @keyframes __demo-ripple { from { transform: scale(.3); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }`;
    document.head.appendChild(style);
    const cursor = document.createElement("div");
    cursor.id = "__demo-cursor";
    cursor.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.8 L10.5 20 L13.3 18.7 L10.4 12.6 L16.5 12.6 Z" fill="#fff" stroke="#222" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
    addEventListener(
      "mousemove",
      (e) => (cursor.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`),
      true,
    );
    addEventListener(
      "mousedown",
      (e) => {
        const ripple = document.createElement("div");
        ripple.className = "__demo-ripple";
        ripple.style.left = `${e.clientX}px`;
        ripple.style.top = `${e.clientY}px`;
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
      },
      true,
    );
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", draw);
  else draw();
}

async function main() {
  await waitForServer();
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/chromium-browser",
    // 日付と時刻の欄を日本の書式（2026/12/30・10:00）で出す
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none", "--lang=ja-JP", "--accept-lang=ja-JP,ja",
      `--window-size=${WIDTH},${HEIGHT}`],
    env: { ...process.env, LANG: "ja_JP.UTF-8", LANGUAGE: "ja_JP:ja", LC_ALL: "ja_JP.UTF-8" },
  });
  const page = await browser.newPage();
  await page.setExtraHTTPHeaders({ "Accept-Language": "ja-JP,ja" });
  // --lang だけではヘッドレスの日付・時刻の欄が英語の書式のままなので、ロケールも上書きする
  const cdp = await page.createCDPSession();
  await cdp.send("Emulation.setLocaleOverride", { locale: "ja-JP" });
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument(installCursor);

  page.on("pageerror", (e) => console.log(`[画面] ${e.message}`));
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const url = req.url();
    if (url.startsWith(AUTH_PUBLIC)) return req.continue({ url: AUTH_INTERNAL + url.slice(AUTH_PUBLIC.length) });
    return req.continue();
  });

  // マウスの位置。ページを移ると矢印が消えるので、移ったあとにここへ戻して出し直す
  let mouse = { x: WIDTH / 2, y: HEIGHT / 2 };
  const moveTo = async (x, y, steps = 28) => {
    await page.mouse.move(x, y, { steps });
    mouse = { x, y };
  };
  const reshowCursor = async () => {
    await page.mouse.move(mouse.x + 1, mouse.y);
    await page.mouse.move(mouse.x, mouse.y);
  };

  const waitForTitle = async (title) => {
    try {
      await page.waitForFunction(
        (t) => document.querySelector("h1.page-title, h1.hero-title")?.textContent.includes(t),
        { timeout: 90000 },
        title,
      );
    } catch {
      const seen = await page.evaluate(() => document.body.innerText.slice(0, 300));
      throw new Error(`「${title}」が出なかった。画面にはこれが出ていた:\n${seen}`);
    }
    await reshowCursor();
    await sleep(800);
  };

  /** 要素を画面内に入れ、矢印を動かしてから押す。 */
  const click = async (selector, { pause = 500 } = {}) => {
    const el = await page.waitForSelector(selector, { visible: true, timeout: 30000 });
    await el.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(700);
    const box = await el.boundingBox();
    await moveTo(box.x + box.width / 2, box.y + box.height / 2);
    await sleep(pause);
    await page.mouse.down();
    await sleep(80);
    await page.mouse.up();
  };

  /** 欄を押して、1文字ずつ打つ。 */
  const type = async (selector, value) => {
    await click(selector, { pause: 250 });
    await page.$eval(selector, (el) => (el.value = ""));
    await page.keyboard.type(value, { delay: 110 });
    await sleep(400);
  };

  /** 画面をなめらかに下へ送る（中身を見せるため）。 */
  const scrollBy = async (dy, ms = 1400) => {
    await page.evaluate((dy) => window.scrollBy({ top: dy, behavior: "smooth" }), dy);
    await sleep(ms);
  };
  const scrollTop = async () => {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    await sleep(1000);
  };
  /** ページの終わりまで少しずつ送る。 */
  const scrollThrough = async (step = 360, ms = 1300, max = 12) => {
    for (let i = 0; i < max; i++) {
      const atEnd = await page.evaluate(() => innerHeight + scrollY >= document.documentElement.scrollHeight - 4);
      if (atEnd) break;
      await scrollBy(step, ms);
    }
    await sleep(800);
  };

  // 録画の前に相談の画面を開いておく（最初の読み込みの白い画面を撮らない）
  await page.goto(`${BASE}/ask`, { waitUntil: "networkidle0" });
  await waitForTitle("相談");
  await page.waitForFunction(() => document.querySelector("#event-options option"));

  const webm = `${OUT}/cos-meguri-demo.webm`;
  const recorder = await page.screencast({ path: webm });
  const started = Date.now();
  const elapsed = () => (Date.now() - started) / 1000;
  console.log("録画開始");
  await sleep(1500);

  // 1. 相談。ログインしないまま使える。空のまま押すと、足りない欄の真下に出る
  await click("#btn-apply");
  await page.waitForSelector(".field-error", { timeout: 20000 });
  await sleep(1800);

  // 2. 条件を埋める。イベント名は略称でよく、欄を離れると目的地と開始・終了が入る
  await type("#slot-event", "コミケ");
  await click("#slot-day", { pause: 200 });
  await page.waitForFunction(() => document.querySelector("#slot-destination").value, { timeout: 20000 });
  await page.$eval("#slot-day", (el) => {
    el.value = "2026-12-30";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await sleep(1200);
  await type("#slot-title", "ブルーアーカイブ");
  await type("#slot-character", "アロナ");
  await type("#slot-station", "横浜");
  await click("#slot-luggage", { pause: 200 });
  await page.select("#slot-luggage", "heavy");
  await page.keyboard.press("Escape");
  await sleep(1000);
  await click("#btn-apply");
  await sleep(1500); // 押したあと「組み立てています…」に変わるところまでは等速で見せる
  const waitFrom = elapsed();

  // 3. プラン（メイクの工程）。組み立てに Gemini と駅すぱあとを呼ぶので少しかかる
  await waitForTitle("プラン");
  await page.waitForSelector("#pane-makeup .step", { timeout: 90000 });
  const waitTo = elapsed();
  await reshowCursor();
  await sleep(1500);
  await scrollThrough();
  await scrollTop();
  // ゲストで ☆ を押すと、ログインすると使えることと登録の入口が出る
  await click("#pane-makeup button.fav");
  await page.waitForSelector("#fav-note a[href^='/signup']", { timeout: 20000 });
  await sleep(2500);

  // 4. プラン（動線）。行きは開始までに着き、帰りは終了後に出る
  await click('.tab[data-tab="route"]');
  await page.waitForSelector("#pane-route .summary", { timeout: 20000 });
  await sleep(1500);
  await scrollThrough();
  await scrollTop();
  await click('#pane-route button.fav[data-direction="outbound"]');
  await page.waitForSelector("#fav-note a[href^='/signup']", { timeout: 20000 });
  await sleep(2000);
  await click("#fav-note a[href^='/signup']");

  // 5. アカウントを作る。組んだプランと、押した ☆ を引き継ぐ
  await waitForTitle("アカウントを作る");
  const email = `demo-${Date.now()}@example.com`;
  const password = "demo-password";
  await type("#fb-email", email);
  await type("#fb-password", password);
  await type("#fb-password-confirm", password);
  await sleep(600);
  await click("#btn-submit");

  // ログインして戻ると、動線（行き）の ☆ は保存済み。メイクの工程の ☆ も押す
  await waitForTitle("プラン");
  await page.waitForSelector('#pane-route button.fav[data-direction="outbound"][aria-pressed="true"]', {
    timeout: 20000,
  });
  await sleep(2000);
  await click('.tab[data-tab="makeup"]');
  await sleep(1000);
  await click("#pane-makeup button.fav");
  await page.waitForSelector('#pane-makeup button.fav[aria-pressed="true"]', { timeout: 20000 });
  await sleep(1800);

  // 6. マイページ。押した ☆ がお気に入りに並ぶ
  await click('a[href="/me"]');
  await waitForTitle("マイページ");
  await page.waitForSelector("#pane-makeup .fav-item", { timeout: 20000 });
  await sleep(1500);
  await click("#pane-makeup .fav-item summary");
  await sleep(1500);
  await scrollThrough();
  await scrollTop();
  await click('.tab[data-tab="route"]');
  await sleep(1500);
  await click("#pane-route .fav-item summary");
  await sleep(1500);
  await scrollThrough();
  await sleep(1500);

  await recorder.stop();
  await browser.close();
  console.log("録画終了");

  // 提出先で再生しやすいよう H.264 の mp4 にする
  const mp4 = `${OUT}/cos-meguri-demo.mp4`;
  // プランの組み立てを待つあいだ（waitFrom〜waitTo）だけ WAIT_SPEED 倍で流す
  const a = waitFrom.toFixed(2);
  const b = waitTo.toFixed(2);
  const filter =
    `[0:v]trim=0:${a},setpts=PTS-STARTPTS[v0];` +
    `[0:v]trim=${a}:${b},setpts=(PTS-STARTPTS)/${WAIT_SPEED}[v1];` +
    `[0:v]trim=start=${b},setpts=PTS-STARTPTS[v2];` +
    `[v0][v1][v2]concat=n=3:v=1:a=0,fps=25[out]`;
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-filter_complex", filter, "-map", "[out]",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", mp4]);
  console.log(`待ち時間 ${(waitTo - waitFrom).toFixed(1)}秒を ${WAIT_SPEED}倍で流した`);
  fs.rmSync(webm);
  console.log(`書き出し: ${mp4}`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
