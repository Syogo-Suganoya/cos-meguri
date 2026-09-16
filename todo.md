# TODO — 次のデプロイまでに手で行うこと

コードの変更（ゲスト利用・お気に入り・ローカルイベント・英語・CD の push トリガー）は済んでいる。
ここに残っているのは、コンソールや GitHub の画面で手を動かす作業だけ。
詳しい手順は [DEPLOY.md](DEPLOY.md) を参照。

## 1. Firebase（必須）

- [ ] **匿名ログインを有効にする**
  Firebase コンソール → Authentication → ログイン方法 →「匿名」を有効化。
  無効のままだと、ログインしていない人が「使ってみる」を押してもログイン画面に飛ばされる。
- [ ] 「メール/パスワード」が有効のままか確認する

## 2. Web API キーの制限（制限をかけている場合だけ）

- [x] `gcloud services api-keys describe` で確認済み。`FIREBASE_WEB_API_KEY`
  （"Browser key (auto created by Firebase)"）には `identitytoolkit.googleapis.com` と
  **`securetoken.googleapis.com`（Token Service API）の両方が入っている。対応不要。**

## 3. CD を有効にする（GitHub）

`deploy.yml` の push トリガーは有効にした。GitHub 側に値が入っていなければ、デプロイはスキップされる。
設定済みの項目は飛ばしてよい。

- [x] Workload Identity 連携とデプロイ用サービスアカウント（DEPLOY.md パターンC の 1・2）を CLI で作成済み。
  `--attribute-condition` はこのリポジトリ（`Syogo-Suganoya/cos-meguri`）限定にしてある。
  併せて `sts.googleapis.com`（Security Token Service）も有効化した
- [x] Settings → Secrets and variables → Actions は入力済み・値も正しいものに更新済み

  | 種別 | 名前 | 値 |
  |---|---|---|
  | Secret | `WIF_PROVIDER` | `projects/719791901304/locations/global/workloadIdentityPools/github/providers/github` |
  | Secret | `WIF_SERVICE_ACCOUNT` | `cos-meguri-deployer@cos-meguri.iam.gserviceaccount.com` |
  | Variable | `FIREBASE_WEB_API_KEY` | 設定済み |
  | Variable | `EKISPERT_MCP_URL` | 設定済み |
  | Variable | `CD_ENABLED` | `true` |

- [x] Settings → Environments に `production` が存在することを確認済み（保護ルールなし）
- [x] main への push で CD が走ることを確認済み（run 35068704372: test ✓ → deploy ✓ → /health ✓）
- [x] Actions タブで「Deploy to Cloud Run」が test → deploy → /health まで緑になることを確認済み

## 4. デプロイ後の確認

- [x] `https://cos-meguri-cddf5sno5q-an.a.run.app/health` の `auth` が `auth:firebase`、`warnings` が空
- [ ] `https://SERVICE_URL/api/auth/config` の `emulator` が `false` で、`refresh_url` がある
- [ ] ログインせずに `/ask` を開くと相談の画面が出る（匿名ログインが効いている）
- [ ] 収載に無いイベント（例: 地元の撮影会 ＋ 目的地 ＋ 時刻）でプランが組める
- [ ] プランの ☆ → 登録 → プランに戻ると、押した ☆ が保存済みになっている
- [ ] 看板の English で画面が英語になり、プランの工程も英語で組み直される
- [ ] スマホで、トップ・相談・プランが崩れない

## 5. 本番に出す前に（任意・推奨）

- [ ] **Gemini の枠を確認する。** 無料枠（1日20回）に開発中に達して 429 が返った。
  ゲストもプランを組めるので、デモで使うなら課金の有効化か枠の引き上げを検討する
  （枠を超えても止まらず、メイクの工程文があらかじめ用意した文面になるだけ）
- [ ] **Gemini と駅すぱあとの APIキーを再発行する。** 以前ログに平文で出たため。
  再発行したら Secret Manager の `GOOGLE_API_KEY` / `EKISPERT_API_KEY` に新しい版を足す
  （Cloud Run は `:latest` を読むので、次のデプロイで切り替わる）
- [ ] 本番の Cloud Run に `FIREBASE_AUTH_EMULATOR_HOST` / `FIREBASE_AUTH_EMULATOR_URL` /
  `FIRESTORE_EMULATOR_HOST` が入っていないことを確認する
- [ ] 手元の `.env` から使っていない `AUTH_MODE` / `DEV_AUTH_SECRET` の行を消す

## 引き継ぎ（あとで）

- ゲストのデータを期限で消す仕組み（Firestore の TTL）
- ゲストのプラン生成の回数制限
- 中韓の対応（サーバの辞書と、画面の `core/en.js` と同じ形の辞書）
