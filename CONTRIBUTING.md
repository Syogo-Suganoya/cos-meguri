# 開発ガイド

コスめぐりに手を入れるときの前提と決めごと。プロダクトの説明は [README.md](README.md)、
仕様と設計判断の背景は [設計書.md](設計書.md)、本番へのデプロイは [DEPLOY.md](DEPLOY.md) を参照。

## 開発環境

**Python はすべて Docker 側で実行する。ローカルに venv を作らない。**
Cloud Run はコンテナデプロイなので、ローカル・CI・本番が同一の Dockerfile を参照する。

```bash
docker compose up api
```

Firestore エミュレータも一緒に立ち上がる（api はエミュレータの起動を待ってから上がる）。
**データはエミュレータに残るので、コンテナを再起動しても消えない。**

`http://localhost:8080` を開く。8080 が埋まっている環境ではホスト側ポートを変える。

```bash
HOST_PORT=8082 docker compose up api
```

`app/` `web/` `tests/` はボリュームマウントしているので、ソースを直せばホットリロードが効く。
依存（`pyproject.toml`）を変えたときだけイメージの作り直しが要る。

```bash
docker compose up -d --build api
```

### compose プロファイル

| コマンド | 内容 |
|---|---|
| `docker compose up api` | API＋エージェント＋PWA＋Firestore エミュレータ |
| `docker compose --profile test run --rm test` | ユニットテスト（インメモリ） |
| `docker compose --profile itest run --rm test-firestore` | Firestore アダプタの結合テスト |
| `docker compose --profile docs run --rm diagram` | アーキテクチャ図の再生成 |

エミュレータのホスト側ポートは既定 `8210`（`FIRESTORE_PORT` で変更できる）。
データを消したいときは `docker compose down` でエミュレータごと落とす。

## 設定と mock / live

APIキーは `.env`（`.env.example` をコピー）から注入する。gitignore 対象。
本番の秘密情報は Secret Manager で管理し、Cloud Run に環境変数として注入する（イメージに焼き込まない）。

外部APIはすべてポート越しに呼び、環境変数1本で mock と live を入れ替える。
**キーが無ければ live 指定でも mock に落として起動を続ける**（デモ当日にキー1本で全部落ちるのを避ける）。
いま何が動いているかは `GET /api/providers` と `/healthz` で見える。

| 環境変数 | mock（既定） | live |
|---|---|---|
| `VTO_MODE` | ハッシュ由来の決定的な擬似応答 | YouCam API |
| `TRANSIT_MODE` | 主要駅の静的グラフ | 駅すぱあと MCP |
| `LLM_MODE` | キーワード抽出・固定文 | Gemini API（`gemini-3.7-flash`） |
| `REPOSITORY` | — | Firestore（既定）。`memory` はテスト専用 |
| `AUTH_MODE` | 開発用ログイン（**ローカル専用**） | Firebase Authentication |

`REPOSITORY` だけは他と向きが逆で、**既定が実装（Firestore）側**。ローカルでもエミュレータを
使い、`memory` はテストだけで使う。プロセスが死ぬと消える保存先を既定にしておくと、
「ローカルでは動くのに本番で消える」類の不具合が見つからないため。

### 認証だけは例外

`AUTH_MODE=dev` はコス名を入れるだけでJWTを発行し、**パスワードを検証しない**。
`APP_ENV` が `local` / `test` 以外のときにこれを指定すると、起動時に例外で止まる
（`adapters/registry.py: build_auth`）。設定ミスで本番に出る事故を潰すため、
この分岐だけは mock フォールバックの対象外にしてある。

live（Firebase Authentication）の経路:

1. フロントが Identity Toolkit の REST を直接叩いて ID トークンを取得（JS SDK も CDN も使わない）
2. 以降のリクエストは `Authorization: Bearer <IDトークン>`
3. バックエンドが firebase-admin で検証し、**uid だけ**を上位へ渡す

メールアドレスは Firebase 側に留め、Firestore へは書かない（設計書 §7-1）。

## ディレクトリ構成

```
app/
├── main.py             Cloud Run のエントリポイント（API＋PWA配信）
├── config.py           mock / live の切り替え（環境変数のみ）
├── domain/             外部APIに依存しない純粋ロジック
│   ├── models.py       設計書 §6 のデータモデル
│   ├── makeup.py       肌タイプ×顔属性のメイク工程分解（★中核）
│   ├── crowd.py        更衣室の混雑予測モデル
│   ├── luggage.py      大荷物制約の経路評価
│   ├── awase.py        合わせの進捗・到着監視・リスケ起案
│   ├── parsing.py      チャットの自由文からの条件抽出（LLM非依存）
│   ├── guardrails.py   二次創作ガイドライン・エンジン（権利物・ボイスクローン）
│   └── events.py       収載イベントのマスタ
├── ports/              外部依存のインターフェース
├── adapters/           mock（既定）と live（YouCam/駅すぱあと/Gemini/Firestore/Firebase Auth）
├── agents/             設計書 §4 のエージェント構成
└── api/                HTTP 層
web/                    PWA（ログイン・チャット・お知らせも自作）
├── index.html          トップ（できること・使い方・ログイン）
├── pages/              login / prep / plan / day の4画面
├── js/core/            全ページ共通（api・認証・枠・チャット・お知らせ・プラン復元）
└── js/pages/           画面ごとの初期化。1画面1モジュール
docs/                   アーキテクチャ図の生成スクリプト
tests/                  ユニット137件＋Firestore結合11件
```

### フロントの決めごと

- **1画面1モジュール。**`<script type="module" src="/static/js/pages/plan.js">` だけを読む。
  バンドラは使わない。ページが持たない要素にハンドラを付けないので、
  「id が無くて例外」で画面全体が死ぬことがない（`core/dom.js` の `on()` がその役）
- **枠（看板・シェブロン・チャット・お知らせ・脚注）は `core/shell.js` と `core/chat.js` が差し込む。**
  HTML を6枚に複製するとズレるので、枠の出どころはここ1箇所
- **`onclick` 属性は使わない。**module スコープの関数は呼べず、押しても無言で何も起きない。
  イベント委譲（`data-*` 属性）で受ける。`tests/test_web_shell.py` が見張っている
- **モジュールの先頭で実行する処理は、参照する `const` より後ろに置く。**
  前に置くと初期化前アクセスで例外になり、その画面だけ丸ごと動かない
- **ページをまたぐ状態は `core/store.js` に集約する。**`exp_id` と `awase_id` だけを控え、
  正はサーバ（`GET /api/chat` の `exp_id`）。合わせは一覧APIが無いので控えが必須
- プランができたら `cosmeguri:expedition` を投げる。開いている画面がその場で描き直す

### 依存の向き

```
agents → ports → adapters
   ↓
domain（外部依存なし・純粋関数）
```

- エージェントは **ports にしか依存しない**。具体的なAPIの名前を知らない
- `domain/` は外部を一切呼ばない。テストしやすさと、API が落ちても機能が残ることの両方がここに乗る
- 新しい外部APIを足すときは「ports に抽象を切る → mock を先に書く → live を足す → registry に登録」の順
- `RepositoryPort` にメソッドを足したら、**インメモリと Firestore の両方**を実装する。
  片方だけだと本番で `NotImplementedError` になる

## 設計上の判断

手を入れるとき、次の6つは意図的な選択なので崩さないでほしい。

**メイク工程は LLM に依存させない。** 骨格は `domain/makeup.py` のルールで決め切り、
Gemini は「言い回しを整える」「母語に落とす」「文化的補足を足す」だけを担う。
LLM が落ちても全工程が出る。件数が変わった LLM 応答は破棄してルールベースの結果を優先する。

**チャットの「次に何を聞くか」も LLM に委ねない。** 抽出だけを LLM に任せ、
不足項目の判定と質問はコード側（`agents/chat.py`）が持つ。聞き漏らしと堂々巡りを避けるため。

**設備情報が取れない区間は保守的に倒す。** 駅すぱあとの応答にEV有無が無い場合、
「EVなし・階段1」として扱う。大荷物ユーザーには楽観的な既定のほうが危険なため。

**Firestore のクエリは単一フィールドの等値だけに絞る。** 複合条件は複合インデックスの
作成をデプロイ手順に増やす。件数が小さいうちは1条件で引いて残りを Python 側で絞るほうが、
運用の手数が少ない（`list_expeditions_on` の status 除外、`list_notifications` の未読絞りが該当）。

**イベント時刻は JST 固定。** 収載イベントはすべて日本開催なので、訪日レイヤーが自国の
タイムゾーンから予定を入れても会場の時刻がずれない。利用者に見せる時刻は必ず
`models.jst_hm()` を通す（クライアントから UTC で届いた値をそのまま書式化すると9時間ずれる）。

## API

利用者向けのエンドポイントはすべて `Authorization: Bearer <IDトークン>` が要る。
誰であるかは必ずトークンから決め、body の `layer_id` は信用しない。

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/auth/config` | ログイン画面が使う公開情報（provider / web APIキー） |
| POST | `/api/auth/dev-login` | 開発用ログイン（`AUTH_MODE=dev` のときだけ有効） |
| POST | `/api/auth/session` | ログイン後にコス名アカウントを引き当てる／作る |
| POST | `/api/chat` | チャット1往復。条件が揃えばプランまで組む |
| GET | `/api/me/notifications` | アプリ内お知らせ（未読数つき） |
| POST | `/api/me/face` | 顔解析。画像は破棄し数値スコアのみ保存 |
| POST | `/api/expeditions` | 遠征プラン一括生成（試着・メイク・動線・更衣室） |
| POST | `/api/expeditions/{id}/day-of` | 当日モードを1回進める（利用者の操作用） |
| POST | `/api/fitting` | 試着候補の提案（権利物ガードを通す） |
| POST | `/api/awase` | 合わせ作成。招集はコス名で行う |
| POST | `/api/awase/{id}/monitor` | 到着監視＋リスケ起案（確定はしない） |
| POST | `/api/awase/{id}/proposals/{pid}/decision` | 主催者の承認/却下 |
| GET | `/api/audit` | 監査ログ |

`/docs`（Swagger UI）でも一覧できる。

## テスト

テストは2種類ある。

```bash
docker compose --profile test run --rm test
```

ユニット・結合テスト（105件）。インメモリで回るので速い。`conftest.py` が保存先を
明示的に `memory` に固定しているため、環境変数の指定漏れで実データベースを触ることはない。

```bash
docker compose --profile itest run --rm test-firestore
```

Firestore アダプタの結合テスト（11件）。エミュレータに実際に読み書きする。
**`adapters/firestore_repo.py` を触ったら必ず通すこと。** ここが無いと
「ローカルでは動くのに本番で壊れる」という一番たちの悪い失敗をする。

**テスト名は設計書の主張をそのまま書く。** 「なにが壊れたら設計上まずいのか」が
名前から読めることを優先している。`tests/conftest.py` の `login` フィクスチャで
ログイン済みクライアントを作れる。

| 設計書 | 実装 | テスト |
|---|---|---|
| §4 エージェント構成 | `agents/` の7エージェント | `test_api.py` |
| §7-1 素顔とコス名の分離 | 画像は解析後に `del`、破棄証跡を audit へ | `test_face_analysis_discards_image_and_logs_it` |
| §7-1 認証 | 保持するのは uid のみ。メールは Firebase 側に留める | `test_account_stores_no_personal_data` |
| §7-2 公平性 | 中庸も含め全工程に個別化根拠。明度を変える指示を出さない | `test_no_skin_lightening_instructions` ほか |
| §7-3 位置共有の時限性 | `LocationShare.expires_at`（失効後は ETA を採らない） | `test_location_share_goes_inactive_after_the_event` |
| §7-4 二次創作ガイドライン | `guardrails.py`。共有テキストからキャラ名を落とす | `test_ip_guard_returns_422` |
| §7-5 リスケの承認制 | 主催者以外は 403。起案だけでは枠が動かない | `test_shoot_does_not_move_until_organizer_approves` |
| §7-6 通知をアプリ内で閉じる | 自律通知はお知らせ欄へ。会場時刻で書く | `test_day_of_alert_lands_in_the_in_app_inbox` |
| §7-7 権限の境界 | 他人の遠征・お知らせ・合わせは見えない | `test_inbox_is_private_to_its_owner` ほか |
| §6 データモデル | Firestore と往復しても入れ子・列挙型が壊れない | `test_firestore.py` |
| §11 生成メディア | キャラ名をプロンプトに入れない。AI生成を明示する | `test_look_prompt_never_contains_the_character_name` |
| §11 ボイスクローン不使用 | 依頼を422で止め、証跡を残す | `test_voice_cloning_is_refused` |

新しい振る舞いを足すときは、**設計書のどの主張を守るテストなのか**が分かる名前にする。

## アーキテクチャ図

図は `diagrams`（graphviz）で生成する。**実装を変えたら描き直す。**

```bash
docker compose --profile docs run --rm diagram
```

生成元は [docs/architecture.py](docs/architecture.py)。日本語ラベルのため Noto CJK を
入れた専用イメージ（[docs/Dockerfile](docs/Dockerfile)）で動かす。
図と実装がずれたらコード側を正とする。

## コードの書きかた

- **コメントと識別子の説明は日本語。** 「何をしているか」ではなく「なぜそうしたか」を書く
- **設計書の条番号を引く。** プライバシー・公平性まわりの分岐には `（設計書 §7-1）` のように根拠を残す
- 型ヒントは全面的に付ける。`from __future__ import annotations` を先頭に置く
- Pydantic モデルはドメインの言葉で名付ける（`Layer` `Awase` `Expedition`）
- 外部APIの失敗は上位に例外を漏らさず、フォールバックを返す。ただし**認証の失敗だけは通す**（401にする）

### 静的ファイルを変えたとき

`web/` を変えたら **`sw.js` の `CACHE` 名を上げる**。CSS は各HTMLのクエリ（`?v=7`）も
`sw.js` の `SHELL` と揃えて上げる。ページのエントリJS（`js/pages/*.js`）にもクエリを付ける。
`core/*` は `import` から読まれるのでクエリは付けない（付けると `import` 側にも書く羽目になる）。

モジュールの更新が届く経路は2つある。どちらか片方でも欠けると、直したはずの
コードが動かない状態で悩むことになる。

- `/static` は `Cache-Control: no-cache` を付けて配信している（`app/main.py` の
  `RevalidatingStaticFiles`）。ブラウザは毎回 ETag で確かめるので、変わっていなければ 304
- Service Worker は `/static` を stale-while-revalidate で扱う。キャッシュを先に返しつつ
  裏で取り直すので、`CACHE` 名の更新を忘れても1回ぶん遅れで新しくなる

ローカルで古いまま動いているように見えたら、DevTools で Service Worker を unregister して
キャッシュを消すのが確実。

## PR を出す前に

1. `docker compose --profile test run --rm test` が通る
2. アーキテクチャに影響する変更なら図を再生成した
3. 設計書の記述と実装がずれていないか確認した（ずれたら設計書も直す）
4. 環境変数や外部サービスを増やしたなら [DEPLOY.md](DEPLOY.md) も直した
5. `.env` や実キーをコミットしていない

## 未検証・引き継ぎ事項

- **ADK は依存に入れているが、まだ使っていない。** オーケストレータは手書きで、
  エージェント間の受け渡しは Python の関数呼び出し。ADK への載せ替えは `agents/` だけで済む形にしてある
- **YouCam / 駅すぱあとの live アダプタは実APIで未検証。** エンドポイントと
  レスポンスのキー名は各モジュール先頭の定数に集約してあり、契約確定後はそこだけ直せばよい
- **Firebase Authentication は実プロジェクトで未検証。** ローカルは開発用ログインで通しており、
  `AUTH_MODE=firebase` の経路（Identity Toolkit REST → firebase-admin 検証）はコードのみ
- **Service Worker の登録は未確認。** `/sw.js` は正しい MIME で配信できているが、
  検証に使った組み込みブラウザが SW 登録を許可しないため、実ブラウザでの確認が要る
- 中韓は `agents/i18n.py` の辞書に列を足せば有効になる（MVPは日英）
