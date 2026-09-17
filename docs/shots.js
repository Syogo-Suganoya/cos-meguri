/**
 * トップページと README に載せる画面操作イメージを撮る。
 *
 *   docker compose up -d api
 *   docker compose --profile shots run --rm shots
 *
 * 利用者と同じ順に操作して撮るので、画面を変えたら撮り直すだけで追随する。
 * ゲストで相談とプランを使い、☆ から登録する流れを撮る。登録は毎回まっさらなメールアドレスなので、
 * エミュレータを空にする必要はない。
 *
 * 出力: web/shots/*.png と web/shots/thumbs/*.png（トップページの「画面」と README が同じ画像を指す）
 */

const fs = require("fs");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE_URL || "http://api:8080";
const OUT = process.env.OUT_DIR || "/work/web/shots";
// ブラウザ向けのエミュレータ URL は http://localhost:9099 で配られる。
// このコンテナの localhost にはエミュレータがいないので、compose の名前へ付け替える
const AUTH_PUBLIC = process.env.AUTH_PUBLIC || "http://localhost:9099";
const AUTH_INTERNAL = process.env.AUTH_INTERNAL || "http://firebase-auth:9099";
const WIDTH = 1120;

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

async function main() {
  await waitForServer();
  fs.mkdirSync(`${OUT}/thumbs`, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/chromium-browser",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: WIDTH, height: 860, deviceScaleFactor: 2 });

  page.on("console", (m) => {
    if (m.type() === "error") console.log(`[画面] ${m.text()}`);
  });
  page.on("pageerror", (e) => console.log(`[画面] ${e.message}`));

  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const url = req.url();
    if (url.startsWith(AUTH_PUBLIC)) return req.continue({ url: AUTH_INTERNAL + url.slice(AUTH_PUBLIC.length) });
    return req.continue();
  });

  /** 画面の高さを決めて撮る。ページ全体の長さに合わせたいときは height を省く。
   *
   * 大きい1枚と、一覧用の小さい1枚（thumbs/）を撮る。トップページは8枚を一覧で出すので、
   * 大きい画像をそのまま並べると2MBを超える。倍率を落とした別画像にして軽くする。
   */
  const shot = async (name, height) => {
    const h = height || (await page.evaluate(() => document.documentElement.scrollHeight));
    for (const [scale, dir] of [[2, OUT], [0.3, `${OUT}/thumbs`]]) {
      await page.setViewport({ width: WIDTH, height: h, deviceScaleFactor: scale });
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500); // 入場のアニメーション（0.24秒）が終わるのを待つ
      await page.screenshot({ path: `${dir}/${name}.png` });
    }
    console.log(`撮影: ${name}.png`);
  };

  /** 見出しの文言で画面が切り替わったかを判断する。 */
  const waitForTitle = async (title) => {
    try {
      await page.waitForFunction(
        (t) => document.querySelector("h1.page-title, h1.hero-title")?.textContent.includes(t),
        { timeout: 60000 },
        title,
      );
    } catch {
      const seen = await page.evaluate(() => document.body.innerText.slice(0, 300));
      throw new Error(`「${title}」が出なかった。画面にはこれが出ていた:\n${seen}`);
    }
    await sleep(600);
  };

  const type = async (selector, value) => {
    await page.waitForSelector(selector, { timeout: 20000 });
    await page.$eval(selector, (el) => (el.value = ""));
    await page.type(selector, value);
  };

  // 1. トップ。「使ってみる」はログインせずに相談へ入る
  await page.goto(`${BASE}/`, { waitUntil: "networkidle0" });
  await waitForTitle("ぜんぶ");
  await shot("01-top", 760);
  await page.click("#btn-start");

  // 2. 相談（ゲストのまま。空のまま押すと、足りない欄の真下に何を入れるかが出る）
  await waitForTitle("相談");
  await page.waitForFunction(() => document.querySelector("#event-options option"));
  await page.click("#btn-apply");
  await page.waitForSelector(".field-error", { timeout: 20000 });
  await shot("02-ask", 860);

  // 条件を埋めて組む
  await type("#slot-event", "コミケ"); // イベント名は自由入力。略称でも収載イベントに当たる
  await page.click("#slot-title"); // 欄を離れると、目的地と開始・終了が自動で入る
  await page.waitForFunction(() => document.querySelector("#slot-destination").value, { timeout: 20000 });
  await page.$eval("#slot-day", (el) => (el.value = "2026-12-30"));
  await type("#slot-title", "ブルーアーカイブ");
  await type("#slot-character", "アロナ");
  await type("#slot-station", "横浜");
  await page.select("#slot-luggage", "heavy");
  await page.click("#btn-apply");

  // 3. プラン（ゲスト・メイクの工程）。組み立てに Gemini と駅すぱあとを呼ぶので時間がかかる。
  //    ☆ を押すと、お気に入りはログインすると使えることと、登録・ログインの入口が出る
  await waitForTitle("プラン");
  await page.waitForSelector("#pane-makeup .step", { timeout: 60000 });
  await page.click("#pane-makeup button.fav");
  await page.waitForSelector("#fav-note a[href^='/signup']", { timeout: 20000 });
  await shot("03-plan-guest-makeup", 860);

  // 4. プラン（ゲスト・動線）。ログインする前に、行き・帰りの動線も見られる
  await page.click('.tab[data-tab="route"]');
  await page.waitForSelector("#pane-route .summary", { timeout: 20000 });
  await page.click('#pane-route button.fav[data-direction="outbound"]');
  await page.waitForSelector("#fav-note a[href^='/signup']", { timeout: 20000 });
  await shot("04-plan-guest-route");
  // 案内のリンクは、最後に押した ☆（動線・行き）をログイン後にそのまま保存する
  await page.click("#fav-note a[href^='/signup']");

  // 5. アカウントを作る（まっさらなアカウントを登録する。組んだプランは引き継ぐ）
  await waitForTitle("アカウントを作る");
  const email = `shots-${Date.now()}@example.com`;
  const password = "shots-password";
  await type("#fb-email", email);
  await type("#fb-password", password);
  await type("#fb-password-confirm", password);
  await shot("05-signup", 760);
  await page.click("#btn-submit");

  // ログイン後は動線（行き）の ☆ が自動で保存されている。メイクの工程は撮影に写さず、
  // ここでログイン後の本物の ☆ として押し直す（ゲストの ☆ は案内を出すだけで保存はしていない）
  await waitForTitle("プラン");
  await page.waitForSelector('#pane-route button.fav[data-direction="outbound"][aria-pressed="true"]', {
    timeout: 20000,
  });
  await page.click('.tab[data-tab="makeup"]');
  await page.waitForSelector("#pane-makeup button.fav", { timeout: 20000 });
  await page.click("#pane-makeup button.fav");
  await page.waitForSelector('#pane-makeup button.fav[aria-pressed="true"]', { timeout: 20000 });

  // 6. マイページ（保存したメイクの工程と動線が並ぶ）
  await page.goto(`${BASE}/me`, { waitUntil: "networkidle0" });
  await waitForTitle("マイページ");
  await page.waitForSelector("#pane-makeup .fav-item", { timeout: 20000 });
  await shot("06-me", 760);

  await browser.close();
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
