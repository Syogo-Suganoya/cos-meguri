# デプロイ手順

コスめぐりを Cloud Run に載せる手順。**CLI（gcloud）** と **画面操作（Google Cloud コンソール）** の
2通りを併記する。どちらでも結果は同じなので、片方だけ実行すればよい。
初回のあと自動化したい場合は **パターンC: GitHub Actions（CD）**（現在オフ）を使う。

開発環境の作り方は [CONTRIBUTING.md](CONTRIBUTING.md)、設計の背景は [設計書.md](設計書.md) を参照。

## 全体像

PWA も API も同じ1サービスから配信する。フロント用のホスティングは要らない。

| 構成要素 | 用途 |
|---|---|
| Cloud Run | API＋エージェント＋PWA（コンテナ1つ） |
| Artifact Registry | コンテナイメージの置き場 |
| Cloud Build | ソースからのイメージビルド |
| Firestore（Native） | レイヤー・遠征・合わせ・お知らせ・チャット・監査ログ |
| Secret Manager | 外部APIキー |
| Firebase Authentication | ログイン |
| Cloud Logging | 監査ログ（Cloud Run から自動で流れる） |

以下、プロジェクトIDは `cos-meguri`、リージョンは東京（`asia-northeast1`）を前提に書く。
イベントが日本開催なので、レイテンシとデータ所在地の両面で東京を選んでいる。

---

# パターンA: CLI（gcloud）

## 0. 準備

```bash
gcloud auth login
gcloud config set project cos-meguri
gcloud config set run/region asia-northeast1
```

必要なAPIを有効化する。

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  identitytoolkit.googleapis.com \
  generativelanguage.googleapis.com
```

実行者には最低限 `roles/run.sourceDeveloper` と `roles/iam.serviceAccountUser` が要る。

## 1. Firestore を作る

```bash
gcloud firestore databases create --location=asia-northeast1
```

データベースIDを省略すると `(default)`、種別は Native モードになる。アプリはこれを前提にしている。

> [!NOTE]
> **Cloud Run には `FIRESTORE_EMULATOR_HOST` を設定しないこと。** 設定されていると
> クライアントが実 Firestore ではなくエミュレータを見にいき、書き込みが行方不明になる。
> ローカルの compose だけがこの変数を渡している。

## 2. 実行用サービスアカウント

既定の Compute Engine サービスアカウントは権限が広すぎるので、専用のものを作る。

```bash
gcloud iam service-accounts create cos-meguri-run \
  --display-name="コスめぐり Cloud Run 実行用"
```

必要なロールだけを付ける。

```bash
for ROLE in roles/datastore.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding cos-meguri \
    --member="serviceAccount:cos-meguri-run@cos-meguri.iam.gserviceaccount.com" \
    --role="$ROLE"
done
```

Firebase の ID トークン検証は Google の公開鍵で行うため、追加のロールは要らない。

## 3. シークレットを登録する

APIキーはイメージに焼き込まず、Secret Manager から注入する。

```bash
printf '%s' 'YOUR_GEMINI_API_KEY' | gcloud secrets create GOOGLE_API_KEY --data-file=-
printf '%s' 'YOUR_YOUCAM_API_KEY' | gcloud secrets create YOUCAM_API_KEY --data-file=-
printf '%s' 'YOUR_YOUCAM_SECRET' | gcloud secrets create YOUCAM_SECRET_KEY --data-file=-
printf '%s' 'YOUR_EKISPERT_KEY' | gcloud secrets create EKISPERT_API_KEY --data-file=-
```

`printf` を使うのは、`echo` だと末尾の改行までシークレットに入ってしまうため。

更新するときは新しいバージョンを足す。

```bash
printf '%s' 'NEW_VALUE' | gcloud secrets versions add GOOGLE_API_KEY --data-file=-
```

## 4. Firebase Authentication を有効にする

ここだけは Firebase コンソールでの操作が要る（gcloud に同等のコマンドが無い）。

1. https://console.firebase.google.com で「プロジェクトを追加」→ **既存の GCP プロジェクトを選択**
2. 左メニュー **Authentication** → 「始める」→ **メール / パスワード** を有効化
3. プロジェクト設定 → 「マイアプリ」→ **ウェブアプリを追加**（`</>`）
4. 表示される `apiKey` を控える（公開前提の値なのでシークレット化しなくてよい）

## 5. デプロイする

ソースから直接デプロイする。Cloud Build がビルドし、Artifact Registry の
`cloud-run-source-deploy` リポジトリに push される（無ければ自動作成）。

```bash
gcloud run deploy cos-meguri \
  --source . \
  --region asia-northeast1 \
  --service-account cos-meguri-run@cos-meguri.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars "APP_ENV=production,AUTH_MODE=firebase,REPOSITORY=firestore,YOUCAM_MODE=live,EKISPERT_MODE=live,GEMINI_MODE=live,GOOGLE_CLOUD_PROJECT=cos-meguri,FIREBASE_PROJECT_ID=cos-meguri,FIREBASE_WEB_API_KEY=YOUR_WEB_API_KEY,GEMINI_MODEL=gemini-3.7-flash,EKISPERT_MCP_URL=https://api-mcp.ekispert.jp/mcp" \
  --update-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest,YOUCAM_API_KEY=YOUCAM_API_KEY:latest,YOUCAM_SECRET_KEY=YOUCAM_SECRET_KEY:latest,EKISPERT_API_KEY=EKISPERT_API_KEY:latest"
```

ポイント:

- `--allow-unauthenticated` は **PWA を一般公開するため**。API の認証はアプリ側（Firebase の
  ID トークン検証）が担う
- `PORT` は Cloud Run が渡す。Dockerfile の `CMD` がそれを読むので指定不要
- **`AUTH_MODE=firebase` は必須**。`APP_ENV=production` で `AUTH_MODE=dev` を指定すると、
  パスワード検証なしのログインが本番に出ないよう、起動時に例外で止まる
- キーが未設定のプロバイダは `live` 指定でも自動的に mock に落ちる。まず全部 mock で出して、
  キーが揃ったものから `live` に切り替えるのが安全
- `REPOSITORY=firestore` は既定値だが、取り違えを防ぐため明示している。`memory` にすると
  インスタンスの再起動でデータが消える（テスト専用）

## 6. 動作確認

```bash
curl -s https://SERVICE_URL/healthz
```

`providers` が期待どおりか見る。`auth` が `auth:dev` になっていたら、`AUTH_MODE` か
Firebase の設定が入っていない（起動時のログに警告が出ているはず）。

```json
{"status":"ok","env":"production","providers":{"youcam":"youcam:live","ekispert":"ekispert:live","gemini":"gemini:live","notifier":"notifier:in_app","repository":"repository:firestore","auth":"auth:firebase"}}
```

ブラウザで `https://SERVICE_URL/login` を開き、メールアドレス入力の欄が出ていれば
Firebase 経路に乗っている（開発用ログインなら「はじめる」ボタンだけの画面が出る）。

---

# パターンB: 画面操作（Google Cloud コンソール）

CLI と同じことを画面から行う。番号はパターンAと対応している。

## 0. 準備

1. https://console.cloud.google.com でプロジェクト `cos-meguri` を選択（無ければ同じIDで新規作成）
2. 上部の検索窓から **「API とサービス」→「ライブラリ」**
3. 次を1つずつ検索して「有効にする」を押す
   - Cloud Run Admin API
   - Cloud Build API
   - Artifact Registry API
   - Firestore API
   - Secret Manager API
   - Identity Toolkit API
   - Generative Language API

## 1. Firestore を作る

1. 検索窓から **Firestore** → 「データベースを作成」
2. モード: **Native モード**
3. ロケーション: **asia-northeast1（東京）**
4. データベースID: `(default)` のまま
5. 「データベースを作成」

## 2. 実行用サービスアカウント

1. **IAM と管理 → サービス アカウント** → 「サービス アカウントを作成」
2. 名前: `cos-meguri-run`
3. 「続行」→ 次のロールを追加
   - Cloud Datastore ユーザー
   - Secret Manager のシークレット アクセサー
   - ログ書き込み
4. 「完了」

## 3. シークレットを登録する

1. **Secret Manager** → 「シークレットを作成」
2. 名前に `GOOGLE_API_KEY`、値に Gemini の APIキーを貼る → 「シークレットを作成」
3. 同様に `YOUCAM_API_KEY` / `YOUCAM_SECRET_KEY` / `EKISPERT_API_KEY` を作る

> 値を貼るときは末尾に改行や空白が入らないよう注意する（コピー時に混入しやすい）。

## 4. Firebase Authentication を有効にする

パターンAの手順4と同じ（Firebase コンソールでの操作）。

## 5. デプロイする

ソースを GitHub に置いている場合は、コンソールから直接ビルドできる。

1. **Cloud Run** → 「サービスを作成」
2. **「ソース リポジトリから継続的にデプロイする」** を選び、「CLOUD BUILD の設定」
   - リポジトリとブランチを選ぶ（初回は GitHub の連携が要る）
   - ビルドタイプ: **Dockerfile**、場所は `/Dockerfile`
3. サービス名: `cos-meguri`、リージョン: `asia-northeast1`
4. 認証: **「未認証の呼び出しを許可」**（PWA を一般公開するため）
5. **「コンテナ、ボリューム、ネットワーキング、セキュリティ」** を開く
   - **セキュリティ** タブ → サービスアカウントに `cos-meguri-run` を選ぶ
   - **変数とシークレット** タブ → 「変数を追加」で次を入れる

     | 名前 | 値 |
     |---|---|
     | `APP_ENV` | `production` |
     | `AUTH_MODE` | `firebase` |
     | `REPOSITORY` | `firestore` |
     | `YOUCAM_MODE` | `live` |
     | `EKISPERT_MODE` | `live` |
     | `GEMINI_MODE` | `live`（下の `GEMINI_MODEL` と1文字違い。取り違えない） |
     | `GOOGLE_CLOUD_PROJECT` | `cos-meguri` |
     | `FIREBASE_PROJECT_ID` | `cos-meguri` |
     | `FIREBASE_WEB_API_KEY` | 手順4で控えた apiKey |
     | `GEMINI_MODEL` | `gemini-3.7-flash` |
     | `EKISPERT_MCP_URL` | `https://api-mcp.ekispert.jp/mcp`（固定） |

   - 同じタブの「シークレットを参照」で、`GOOGLE_API_KEY` / `YOUCAM_API_KEY` /
     `YOUCAM_SECRET_KEY` / `EKISPERT_API_KEY` を
     **環境変数として** 公開する（バージョンは `latest`）
6. 「作成」

ローカルのソースから出したい場合は、パターンAの `gcloud run deploy --source .` を使う
（コンソールにローカルフォルダをアップロードする導線は無い）。

## 6. 動作確認

1. **Cloud Run → cos-meguri** のページ上部に出ている URL を開く
2. 末尾に `/healthz` を付けて、`providers` が期待どおりか確認する
3. **ログ** タブで起動時の警告（`... が未設定のため mock で起動します`）が出ていないか見る

---

# パターンC: GitHub Actions（CD）

[.github/workflows/deploy.yml](.github/workflows/deploy.yml) に、テスト → デプロイ →
`/healthz` 確認までを通す CD を置いてある。やっていることはパターンAの手順5と同じで、
**手順0〜4（API有効化・Firestore・サービスアカウント・シークレット・Firebase Auth）は
先に済ませておく必要がある**。

> [!NOTE]
> **この CD は現在オフにしてある。** push トリガーはコメントアウト済みで、
> `deploy` ジョブも変数 `CD_ENABLED` が `true` のときだけ動く。
> 今の状態で走らせても、テストだけ通って `deploy` はスキップされる。

## 何をするワークフローか

| ジョブ | 内容 |
|---|---|
| `test` | `compose --profile test`（インメモリ）と `--profile itest`（Firestore エミュレータ）を実行。APIキーは要らない |
| `deploy` | Workload Identity 連携で認証し、`--source .` で Cloud Run にデプロイ。環境変数とシークレット参照は手順5と同じ |
| 最後のステップ | 新リビジョンの `/healthz` を叩き、`auth:firebase` でなければ失敗させる |

サービスアカウントキーの JSON は保存しない。GitHub の OIDC トークンを
Workload Identity プールで短命の資格情報に交換する。

## 有効化するとき

**1. Workload Identity 連携を作る**

```bash
gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == 'Syogo-Suganoya/cos-meguri'"
```

`--attribute-condition` を省略しないこと。省くと**任意のリポジトリ**がこのプールで
資格情報を取得できてしまう。

**2. デプロイ用サービスアカウントを作り、リポジトリだけに借用を許す**

```bash
PROJECT_NUMBER=$(gcloud projects describe cos-meguri --format='value(projectNumber)')

gcloud iam service-accounts create cos-meguri-deployer

for ROLE in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer roles/storage.admin roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding cos-meguri \
    --member="serviceAccount:cos-meguri-deployer@cos-meguri.iam.gserviceaccount.com" \
    --role="$ROLE"
done

gcloud iam service-accounts add-iam-policy-binding \
  cos-meguri-deployer@cos-meguri.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/Syogo-Suganoya/cos-meguri"
```

`roles/iam.serviceAccountUser` は、実行用の `cos-meguri-run` を Cloud Run に
割り当てるために要る。これが無いとデプロイだけ通って権限エラーになる。

**3. GitHub 側に値を入れる**（Settings → Secrets and variables → Actions）

| 種別 | 名前 | 値 |
|---|---|---|
| Secret | `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| Secret | `WIF_SERVICE_ACCOUNT` | `cos-meguri-deployer@cos-meguri.iam.gserviceaccount.com` |
| Variable | `FIREBASE_WEB_API_KEY` | 手順4で控えた apiKey（公開前提の値なので Variable でよい） |
| Variable | `EKISPERT_MCP_URL` | `https://api-mcp.ekispert.jp/mcp`（固定） |
| Variable | `CD_ENABLED` | `true` ← **これを入れるまでデプロイは走らない** |

**4. トリガーを開ける**

`deploy.yml` の `push:` ブロックのコメントを外す。main への push（`*.md` と `docs/` を除く）で
デプロイが走るようになる。

## 止めかた

`CD_ENABLED` を消すか `false` にすれば、ワークフローは走ってもデプロイはスキップされる。
完全に止めるなら GitHub の **Actions タブ → 該当ワークフロー → Disable workflow**。

---

# 本番前のチェック

`/healthz` の `warnings` に、設定の取り違えが出る。**空配列であることを確認する。**

```bash
curl -s https://SERVICE_URL/healthz | python3 -m json.tool
```

| warnings に出るもの | 意味 | 対処 |
|---|---|---|
| 開発用ログイン（パスワード検証なし）… | `AUTH_MODE=firebase` が効いていない | Firebase の設定を入れ直す |
| `xxx: live 指定ですがキーが無いため mock…` | シークレットの参照漏れ | `--update-secrets` の綴りを確認 |

あわせて次を確認する。

1. ブラウザでログインし、遠征を1件作って `/api/me/notifications` が引けること
2. `providers.repository` が `repository:firestore` になっていること
   （`repository:memory` だとインスタンス再起動でデータが消える）

## エンドポイントの保護の考えかた

| 対象 | 守りかた |
|---|---|
| 利用者向けAPI | Firebase の ID トークン検証（アプリ側） |
| PWA・`/healthz`・`/api/auth/config` | 公開 |

Cloud Run の IAM（`--allow-unauthenticated` を外す方法）は使えない。PWA を
ブラウザから直接開かせる以上、サービス自体は公開せざるを得ないため。

---

# 更新デプロイ

同じコマンドを再実行すれば新しいリビジョンに置き換わる。

```bash
gcloud run deploy cos-meguri --source . --region asia-northeast1
```

環境変数やシークレットは前のリビジョンから引き継がれるので、変更するときだけ指定する。
画面からは **Cloud Run → cos-meguri → 「新しいリビジョンの編集とデプロイ」**。

問題が出たら前のリビジョンに戻す。

```bash
gcloud run services update-traffic cos-meguri --to-revisions=REVISION_NAME=100
```

画面では **「リビジョン」タブ → トラフィックを管理**。

# トラブルシュート

| 症状 | 見るところ |
|---|---|
| 起動しない | Cloud Run の「ログ」。`AUTH_MODE=dev` を本番で指定すると意図的に例外で止まる |
| `providers` が全部 mock | 環境変数の綴りとシークレットの参照。キーが無いと live 指定でも mock に落ちる |
| ログインできない | Firebase コンソールで「メール/パスワード」が有効か、`FIREBASE_WEB_API_KEY` が正しいか |
| 401 が返る | ID トークンの期限切れ。PWA は自動でログアウトして再ログインを促す |
| Firestore の書き込みが失敗 | 実行サービスアカウントに `roles/datastore.user` が付いているか |
| 書き込んだデータが見つからない | `FIRESTORE_EMULATOR_HOST` が設定されていないか確認（本番では未設定が正しい） |
| 再起動でデータが消える | `providers.repository` が `repository:memory` になっている |
| ビルドが失敗 | Cloud Build のログ。`pyproject.toml` の依存解決で落ちていることが多い |
| 画面が古いまま | `web/` を変えたら `sw.js` の `CACHE` 名を上げる。CSS は各HTMLのクエリ（`?v=`）と `SHELL` も揃える |
| ページが404 | `main.py` の `PAGES` に入っているか。HTML・ルート・`sw.js` の `SHELL` は3つセットで直す |
