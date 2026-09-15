# 開発ガイド

コスめぐりに手を入れるときの前提と決めごと。プロダクトの説明は [README.md](README.md)、
仕様と設計判断の背景は [設計書.md](設計書.md)、本番へのデプロイは [DEPLOY.md](DEPLOY.md) を参照。

## 開発環境

**Python はすべて Docker 側で実行する。ローカルに venv を作らない。**
Cloud Run はコンテナデプロイなので、ローカル・CI・本番が同一の Dockerfile を参照する。

```bash
docker compose up api
```

Firestore と Firebase Authentication のエミュレータも一緒に立ち上がる（api は両方の起動を待ってから上がる）。
**データは Firestore エミュレータに残るので、コンテナを再起動しても消えない。**
ログインのアカウントは認証エミュレータがメモリに持つので、`docker compose down` で消える。

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
| `docker compose up api` | API＋エージェント＋PWA＋Firestore と認証のエミュレータ |
| `docker compose --profile test run --rm test` | ユニットテスト（インメモリ） |
| `docker compose --profile itest run --rm test-firestore` | Firestore アダプタの結合テスト |
| `docker compose --profile docs run --rm diagram` | アーキテクチャ図の再生成 |
| `docker compose --profile shots run --rm shots` | 画面操作イメージの撮影（api を起動しておく。`docs/shots/` に出る） |

ホスト側ポートは Firestore エミュレータが既定 `8210`（`FIRESTORE_PORT`）、認証エミュレータが既定 `9099`（`AUTH_EMULATOR_PORT`）。
データを消したいときは `docker compose down` でエミュレータごと落とす。

## 設定と mock / live

APIキーは `.env`（`.env.example` をコピー）から注入する。gitignore 対象。
本番の秘密情報は Secret Manager で管理し、Cloud Run に環境変数として注入する（イメージに焼き込まない）。

外部APIはすべてポート越しに呼び、環境変数1本で mock と live を入れ替える。
**キーが無ければ live 指定でも mock に落として起動を続ける**（デモ当日にキー1本で全部落ちるのを避ける）。
いま何が動いているかは `GET /api/providers` と `/healthz` で見える。

| 環境変数 | mock（既定） | live |
|---|---|---|
| `EKISPERT_MODE` | 主要駅の静的グラフ | 駅すぱあと MCP |
| `GEMINI_MODE` | 固定文 | Gemini API（`gemini-3.7-flash`） |
| `REPOSITORY` | — | Firestore（既定）。`memory` はテスト専用 |
| `AUTH_MODE` | —（`dev` はテスト専用） | Firebase Authentication（ローカルはエミュレータ） |

変数名は**使う API の名前**にしてある。`VTO` / `TRANSIT` / `LLM` は業界の略語で、
何が動くのか名前から分からなかったため。`/healthz` の `providers` もキーを同じ名前に
揃えてあり、値（`ekispert:mock` / `ekispert:live`）が変数の実効値になる。

> [!WARNING]
> **旧名 `VTO_MODE` / `TRANSIT_MODE` / `LLM_MODE` は無効になった。** 設定は
> `extra="ignore"` なので、古い `.env` を使い続けると**エラーにならず既定の mock に落ちる**。
> 手元の `.env` を書き換えること。`GEMINI_MODE`（mock/live）と `GEMINI_MODEL`（モデルID）は
> 1文字違いだが、取り違えると Literal 検証で起動時に落ちるので黙って通ることはない。

`REPOSITORY` だけは他と向きが逆で、**既定が実装（Firestore）側**。ローカルでもエミュレータを
使い、`memory` はテストだけで使う。プロセスが死ぬと消える保存先を既定にしておくと、
「ローカルでは動くのに本番で消える」類の不具合が見つからないため。

### 認証だけは例外

ローカルも本番も **Firebase Authentication** で、ローカルは compose の認証エミュレータ（`firebase-auth`）に繋ぐ。
エミュレータは本番と同じ Identity Toolkit の REST を喋るので、ログイン画面もトークンの検証も同じコードで通る。
違うのは URL だけで、`FIREBASE_AUTH_EMULATOR_HOST`（サーバから見た場所）と
`FIREBASE_AUTH_EMULATOR_URL`（ブラウザから見た場所）で切り替わる。

認証は mock に落とさない。次はどれも**起動時に例外で止まる**（`adapters/registry.py: build_auth`）。

- `AUTH_MODE=dev`（名前を渡すだけで JWT を発行し、**パスワードを検証しない**）を `APP_ENV=test` 以外で指定した
- **エミュレータの変数**を `APP_ENV` が local/test 以外で指定した。firebase-admin はこの変数があると
  **署名の無いトークンを通す**ので、本番に紛れると誰でもなりすませる
- `FIREBASE_PROJECT_ID` / `FIREBASE_WEB_API_KEY` が無い

Firebase Authentication の経路:

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
│   ├── makeup.py       キャラの色味・造形からのメイク工程分解（★中核）
│   ├── luggage.py      大荷物制約の経路評価
│   ├── favorites.py    お気に入りの写しを作る（見出しはキャラ名・イベント・日付）
│   ├── guardrails.py   共有テキストからキャラ名・作品名を落とす（§7-4）
│   └── events.py       収載イベントのマスタ（相談の欄の自動入力に使う。無いイベントも組める）
├── ports/              外部依存のインターフェース
├── adapters/           mock（既定）と live（駅すぱあと/Gemini/Firestore/Firebase Auth）
├── agents/             設計書 §4 のエージェント構成
└── api/                HTTP 層
web/                    PWA（ログインも自作）
├── index.html          トップ（できること・使い方・ログイン）
├── pages/              ask / login / signup / plan / me の5画面
├── js/core/            全ページ共通（api・認証・枠・プラン復元）
└── js/pages/           画面ごとの初期化。1画面1モジュール
docs/                   アーキテクチャ図と画面操作イメージ（shots.js・shots/）の生成
docker/                 認証エミュレータと撮影用のイメージ
tests/                  ユニット100件＋Firestore結合11件
```

### フロントの決めごと

- **1画面1モジュール。**`<script type="module" src="/static/js/pages/plan.js">` だけを読む。
  バンドラは使わない。ページが持たない要素にハンドラを付けないので、
  「id が無くて例外」で画面全体が死ぬことがない（`core/dom.js` の `on()` がその役）
- **枠（看板・シェブロン）の中身は `core/shell.js` が描く。**HTML をページごとに複製するとズレるので、中身の出どころはここ1箇所。
  ただし**置き場所（空の `<header class="top">` と `<nav class="rail" data-step>`）は各ページの HTML に先に置く。**
  通信を待ってから差し込むと、最初の一瞬は本文が左上に詰まって描かれ、画面遷移のたびに表示が飛ぶ。
  看板の右端を出すページは `data-authed` を付ける。ログイン済みならマイページ・ログアウト、ゲストならログイン・新規登録を、
  手元の控え（`store.isMember()`）で通信を待たずに描き分ける（`test_frame_space_is_reserved_before_any_script_runs`）
- **ゲスト。**`/ask` と `/plan` は `requireSession()`。通行証が無ければ匿名ログインでゲストの通行証を取る。
  `/me` は `requireMember()` で、ゲストは `/login?need=member` へ送る。ID トークンは1時間で切れるので、
  401 は `core/api.js` が更新用トークンで1回だけ更新してから投げ直す。登録・ログインの直後は
  `startSession()` が `/api/auth/adopt` でゲストの条件とプランを引き取る
- **条件の入口は `/ask` の欄だけ。**自由文の読み取りは取り下げた（読み違いを確かめて直す
  往復が要らなくなる）。「この条件で組む」でプランが組めたら `/plan` へ移る。留めると、押したのに
  何も起きなかったように見える
- **`onclick` 属性は使わない。**module スコープの関数は呼べず、押しても無言で何も起きない。
  イベント委譲（`data-*` 属性）で受ける。`tests/test_web_shell.py` が見張っている
- **モジュールの先頭で実行する処理は、参照する `const` より後ろに置く。**
  前に置くと初期化前アクセスで例外になり、その画面だけ丸ごと動かない
- **フォームの誤りは2か所にしか出さない。**欄の不足や形の誤りはその欄の真下（`fieldError`）、
  サーバの返事・通信の失敗・できあがりの知らせはフォームの頭（`formAlert`）。どちらも `core/dom.js`。
  画面ごとに違う場所に出すと、押したあとに毎回探させる。ブラウザの吹き出しは使わない（`novalidate`）
- **ページをまたぐ状態は `core/store.js` に集約する。**`exp_id` だけを控え、
  正はサーバ（`GET /api/chat` の `exp_id`）
- プランができたら `cosmeguri:expedition` を投げる。開いている画面がその場で描き直す
- **画面の文言は日英。**訳の鍵は日本語の原文で、訳は `web/js/core/en.js`。
  HTML は `data-i18n="原文"`（子要素の無い要素）・`data-i18n-html="鍵"`（`<b>` などを含む文）・
  `data-i18n-placeholder` / `data-i18n-aria-label` で印を付け、JS の文言は `t("原文", {変数})` を通す。
  文言を足したら en.js にも足す。印や訳の漏れは `tests/test_i18n.py` が落とす。
  言語は端末に控え（ログインしていなくても英語で見られる）、通行証があればサーバにも伝えて、
  組み上がったプランをその言語で組み直す。サーバの誤りは `detail.code` を `core/api.js` が言い直す

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

**条件は LLM に読み取らせない。** 自由文から条件を抜き出す入口は取り下げ、欄で直接受ける。
不足の判定は `ChatSlots.missing()` が持つ。読み違いを利用者に確かめさせる往復が要らなくなる。

**API に無いものは持たない。** 駅設備（エレベータ・階段・コインロッカー）は駅すぱあと API に
データが無いので、アプリからも扱わない。こちらで埋めると「EVで行ける」と表示しておいて
実際は階段だった、という一番まずい外し方をする。大荷物のしんどさは**乗換の回数**で測る（乗換1回ごとに体感時間を足す）。
経路は「大荷物での体感時間が短い順」で選ぶ（`luggage.prefer_easiest`）。
乗換の少なさを絶対視はしない——直通60分と乗換2回30分なら後者が正しいので、
乗換の重さはペナルティ側で表現している。

**Firestore のクエリは単一フィールドの等値だけに絞る。** 複合条件は複合インデックスの
作成をデプロイ手順に増やす。件数が小さいうちは1条件で引いて残りを Python 側で絞るほうが、
運用の手数が少ない（`list_audit` の本人絞りが該当）。

**イベント時刻は JST 固定。** 収載イベントはすべて日本開催なので、訪日レイヤーが自国の
タイムゾーンから予定を入れても会場の時刻がずれない。利用者に見せる時刻は必ず
`models.jst_hm()` を通す（クライアントから UTC で届いた値をそのまま書式化すると9時間ずれる）。

## API

利用者向けのエンドポイントはすべて `Authorization: Bearer <IDトークン>` が要る。
誰であるかは必ずトークンから決め、body の `layer_id` は信用しない。

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/auth/config` | ログイン画面が使う公開情報（provider / web APIキー / 登録・ログイン・トークン更新の URL） |
| POST | `/api/auth/dev-login` | テスト用ログイン（`APP_ENV=test` かつ `AUTH_MODE=dev` のときだけ有効） |
| POST | `/api/auth/session` | ログイン後に uid からアカウントを引き当てる／作る。`guest` はゲスト（匿名ログイン）かどうか |
| POST | `/api/auth/adopt` | ゲストのあいだに組んだ条件とプランを本人へ移す（body の `guest_token` は匿名ログインのものだけ受ける） |
| GET | `/api/chat` | いまの条件と、足りない項目（`missing`） |
| PATCH | `/api/chat/slots` | 条件を書き換える（相談の欄から）。揃えばプランまで組む。イベントは `event_name`（自由入力）・`destination_station`・`starts_time`/`ends_time`（HH:MM）で受ける。収載イベントに当たれば、空の目的地・時刻をマスタで埋める。終了 ≤ 開始は 422（`detail.field`） |
| GET | `/api/events/match?name=` | イベント名を収載イベントに引き当てる（略称も）。相談の画面の自動入力用。無ければ `{"event": null}` |
| GET | `/api/stations?name=` | 書きかけの駅名から正式な駅名の候補（駅すぱあと `get_stations`）。通行証（ゲスト可）が要る |
| POST | `/api/expeditions` | 遠征プラン一括生成（メイク・動線）。`event_id` だけでも、名前＋目的地＋開始・終了でも組める |
| GET | `/api/expeditions/{id}` | プランを引く（本人のものだけ） |
| GET | `/api/me/favorites` | 本人のお気に入り（新しい順）。お気に入りの3本はゲストだと 403（`detail.reason: guest`） |
| POST | `/api/me/favorites` | プランの一部（`kind`: makeup / route、route は `direction`）を写して保存。同じ部分は1件のまま |
| DELETE | `/api/me/favorites/{id}` | お気に入りを消す（本人のものだけ。他人のものは 404） |
| GET | `/api/audit` | 監査ログ |

`/docs`（Swagger UI）でも一覧できる。

## テスト

テストは2種類ある。

```bash
docker compose --profile test run --rm test
```

ユニット・結合テスト（100件）。インメモリで回るので速い。`conftest.py` が保存先を
明示的に `memory` に固定しているため、環境変数の指定漏れで実データベースを触ることはない。
ログインもテスト用の実装（`AUTH_MODE=dev`）に固定しているので、認証エミュレータは要らない。

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
| §4 エージェント構成 | `agents/`（Orchestrator・メイク・動線・多言語・相談） | `test_api.py` `test_ask.py` |
| §7-1 素顔と名前を持たない | 顔写真を受け取る経路も、名前の欄も持たない | `test_account_stores_no_personal_data` |
| §7-1 認証 | 保持するのは uid のみ。メールは Firebase 側に留める。パスワード無しのログインとエミュレータは外に出さない | `test_auth.py` |
| §7-2 公平性 | 顔を見ない。明度を変える指示を出さない | `test_nothing_claims_to_have_measured_the_face` ほか |
| §7-4 二次創作ガイドライン | `guardrails.py`。共有テキストからキャラ名を落とす | `test_character_names_are_stripped_from_shared_text` |
| §7-4 キャラ名は本人のお気に入りの見出しにだけ | 見出しはキャラ名（作品名）・イベント・日付。遠征の応答と他人の一覧には出ない | `test_favorite_titles_name_the_character_for_their_owner` `test_character_name_still_stays_out_of_the_shared_plan` |
| §7-7 権限の境界 | 他人の遠征・条件・お気に入り・記録は見えない | `test_expedition_is_not_readable_by_others` `test_others_cannot_save_read_or_delete_my_favorites` |
| §7-7 ゲスト | ゲストは相談とプランだけ。引き継ぎはゲストのトークンからだけで、他人の条件は吸い上げられない | `test_guest.py` |
| §6 データモデル | Firestore と往復しても入れ子・列挙型が壊れない | `test_firestore.py` |

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
- Pydantic モデルはドメインの言葉で名付ける（`Layer` `Expedition` `ChatSlots`）
- 外部APIの失敗は上位に例外を漏らさず、フォールバックを返す。ただし**認証の失敗だけは通す**（401にする）

### 静的ファイルを変えたとき

`web/` を変えたら **`sw.js` の `CACHE` 名を上げる**。CSS は各HTMLのクエリ（`?v=7`）も
`sw.js` の `SHELL` と揃えて上げる。ページのエントリJS（`js/pages/*.js`）にもクエリを付ける。
`core/*` は `import` から読まれるのでクエリは付けない（付けると `import` 側にも書く羽目になる）。

モジュールの更新が届く経路は2つある。どちらか片方でも欠けると、直したはずの
コードが動かない状態で悩むことになる。

- `/static` は `Cache-Control: no-cache` を付けて配信している（`app/main.py` の
  `RevalidatingStaticFiles`）。ブラウザは毎回 ETag で確かめるので、変わっていなければ 304
- Service Worker はページも `/static` も**ネットワーク優先**で、繋がらないときだけキャッシュを返す。
  以前のキャッシュ優先（裏で取り直す）は変更が1回ぶん遅れて届き、消したフッターが残り続けたのでやめた

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
- **顔を見る機能は持たない。** 肌タイプ判定（YouCam）を外したので、メイク工程は
  キャラの色味・造形だけで組む。顔写真を受け取る経路がアプリのどこにも無い
- **駅すぱあと MCP は実キーで経路探索まで疎通を確認した。** ダイヤ探索（時刻指定）は契約に無く、`plain` に落として引いている。
  応答の読み取りだけは `tests/test_ekispert.py` がドキュメントの例で検証している。
  **運行情報（遅延）は扱わない。** MCP に Tool が無く、REST のレスキューナウも契約外で 403 だった。
  遅延の通知ごとアプリから外した。
  **駅設備（EV・階段・ロッカー）は API 自体に無いので、機能ごと持たない**
- **Firebase Authentication は実プロジェクトで未検証。** ローカルの認証エミュレータでは登録・ログイン・
  誤入力・重複登録まで通している。実プロジェクトとの違いはトークンの署名（エミュレータは署名なし）で、
  署名つきトークンの検証は本番で初めて通る。ゲスト（匿名ログイン）とトークンの更新もエミュレータでだけ確かめている
- **Service Worker の登録は未確認。** `/sw.js` は正しい MIME で配信できているが、
  検証に使った組み込みブラウザが SW 登録を許可しないため、実ブラウザでの確認が要る
- 中韓はまだ無い。サーバは `agents/i18n.py` と工程・注意書きの英語の分岐、画面は `core/en.js` と同じ形の辞書が要る（MVPは日英）
- **駅名・路線名は駅すぱあとの日本語表記のまま出す。**英語の画面でも経路の駅名は日本語。
  「Yokohama」のようなローマ字は、駅の候補が1つに絞れれば正式名で探し直す（「Tokyo」「Omiya」は候補が引けない）
