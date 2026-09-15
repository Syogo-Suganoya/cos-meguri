/* 英語の訳。鍵は日本語の原文（HTML の data-i18n と、JS の t("…")）。
   data-i18n-html の鍵（home.hero.title など）だけは、英語の HTML を持つ。
   鍵が足りないと tests/test_i18n.py が落ちる。 */

export const EN = {
  // ---- 枠
  "コスめぐり": "Cos-Meguri",
  "マイページ": "My page",
  "ログアウト": "Log out",
  "ログイン": "Log in",
  "新規登録": "Sign up",
  "相談": "Plan setup",
  "プラン": "Plan",
  "（できています）": " (done)",
  "進みぐあい": "Progress",

  // ---- <title>
  "コスめぐり — レイヤーの一日エージェント": "Cos-Meguri — a day planner for cosplayers",
  "相談 — コスめぐり": "Plan setup — Cos-Meguri",
  "プラン — コスめぐり": "Plan — Cos-Meguri",
  "ログイン — コスめぐり": "Log in — Cos-Meguri",
  "アカウントを作る — コスめぐり": "Create an account — Cos-Meguri",
  "マイページ — コスめぐり": "My page — Cos-Meguri",

  // ---- トップ
  "レイヤーの一日エージェント": "A day planner for cosplayers",
  "home.hero.title": "Your <em>whole</em> day,<br>in one place.",
  "home.hero.lead":
    "Enter the event, date, character, departure station and luggage, <br>and get your makeup steps and your route there and back.",
  "本名も素顔も預かりません": "No real names, no bare faces",
  "顔写真は受け取りません": "No face photos",
  "位置は受け取りません": "No location tracking",
  "使ってみる": "Try it",
  "こんなときに": "Made for moments like",
  "home.feature.makeup.title": "Where do I even start<br>with this character's makeup?",
  "home.feature.makeup.body":
    "From the character's hair and eye colours, we lay out nine steps in order, from base to wig line. Your skin's lightness stays as it is — the character's tone comes from light and shadow.",
  "home.feature.route.title": "Heavy luggage, yet the route<br>has transfer after transfer",
  "home.feature.route.body":
    "We add time for your luggage at every transfer before comparing routes, so transfer-heavy routes lose out. Departure is worked back from that total, so you still arrive on time.",
  "home.feature.privacy.title": "Handing over a face photo<br>feels wrong in the first place",
  "home.feature.privacy.body":
    "There is simply no feature that takes face photos or locations. The app only receives the conditions needed to build your plan. No name either.",
  "コミックマーケット": "Comic Market",
  "世界コスプレサミット": "World Cosplay Summit",
  "ホココス": "Hokokos",
  "使い方": "How it works",
  "home.howto.1":
    "<b>Fill in the plan setup.</b> Event name, date, destination, times, series, character, departure station and luggage. Listed events like Comic Market fill in the destination and times for you. Local events work too — just enter the nearest station and the times.",
  "home.howto.2":
    "<b>Check your plan.</b> It comes in two parts: makeup steps and route. Want a change? Edit just one field in plan setup and rebuild.",
  "home.howto.3":
    "<b>Keep what you like with ☆.</b> Log in to save makeup steps and routes to favourites and revisit them any time on My page. A plan you built before logging in carries over.",

  // ---- 相談
  "ask.lead": "Fill in the fields and press “Build my plan” — we put the day together and take you to your <b>plan</b>.",
  "条件": "Conditions",
  "あとから1つだけ直して組み直すこともできます。": "You can change a single field later and rebuild.",
  "イベント名": "Event name",
  "日付": "Date",
  "目的地（最寄り駅）": "Destination (nearest station)",
  "開始": "Starts",
  "終了": "Ends",
  "作品名": "Series",
  "キャラ名": "Character",
  "出発駅": "Departure station",
  "荷物": "Luggage",
  "例: コミケ": "e.g. Comic Market",
  "例: 国際展示場": "e.g. Kokusaitenjijo or 国際展示場",
  "例: ブルーアーカイブ": "e.g. Blue Archive",
  "例: アロナ": "e.g. Arona",
  "例: 横浜": "e.g. Yokohama or 横浜",
  "手荷物だけ": "Hand luggage only",
  "キャリー1個": "One suitcase",
  "キャリー＋ウィッグ＋大道具": "Suitcase + wig + large props",
  "この条件で組む": "Build my plan",
  "組み立てています…": "Building…",
  "イベント名を入れてください。": "Enter the event name.",
  "日付を入れてください。": "Enter the date.",
  "目的地の最寄り駅を入れてください。": "Enter the destination's nearest station.",
  "開始の時刻を入れてください。": "Enter the start time.",
  "終了の時刻を入れてください。": "Enter the end time.",
  "作品名を入れてください。": "Enter the series.",
  "キャラ名を入れてください。": "Enter the character.",
  "出発駅を入れてください。": "Enter your departure station.",
  "荷物を選んでください。": "Choose your luggage.",
  "この条件でプランができています。": "Your plan is ready with these conditions. ",
  "プランを見る": "View plan",
  "終了は開始より後の時刻にしてください。": "The end time must be after the start time.",
  "時刻は HH:MM の形で入れてください。": "Enter times as HH:MM.",

  // ---- プラン
  "相談で組み立てた一日ぶん。条件を直すと、ここも組み直します。":
    "Your day, built from plan setup. Change the conditions and this is rebuilt too.",
  "ログインすると、メイクの工程と動線を ☆ でお気に入りに残せます。いま組んだプランもそのまま引き継ぎます。":
    "Log in to save makeup steps and routes to favourites with ☆. The plan you just built carries over.",
  "メイクの工程": "Makeup steps",
  "動線": "Route",
  "plan.note": "Want to change the date or departure station? Edit it in <a href=\"/ask\">plan setup</a>.",
  "まだプランがありません。「相談」で条件をそろえると、ここに出ます。":
    "No plan yet. Fill in the conditions in plan setup and it will show up here.",
  "相談をひらく": "Open plan setup",
  "行きの動線": "outbound route",
  "帰りの動線": "return route",
  "{what}をお気に入りから外す": "Remove {what} from favourites",
  "{what}をお気に入りに保存": "Save {what} to favourites",
  "保存済み": "Saved",
  "お気に入り": "Favourites",
  "お気に入りから外しました。": "Removed from favourites.",
  "お気に入りに保存しました。": "Saved to favourites.",
  "マイページで見る": "View on My page",
  "お気に入りはログインすると使えます。入ったあと、この ☆ をそのまま保存します。":
    "Log in to use favourites. Once you're in, we'll save this ☆ for you.",
  "お気に入りはログインすると使えます": "Log in to use favourites.",
  "お気に入りに保存してあります。": "Already in your favourites.",
  "ログインしました。☆ を押したものをお気に入りに保存しました。": "You're logged in. We saved the ☆ you picked to favourites.",
  "{n}分": "{n} min",
  "分": "min",
  "工程": "steps",
  "ステップの数": "Steps",
  "ぜんぶで": "In total",
  "この工程の決めかた": "How these steps are decided",
  "出発 → 到着": "Depart → Arrive",
  "実際（ふつう {base}分 ＋ 荷物 {extra}分）": "Actual (usual {base} min + luggage {extra} min)",
  "実際にかかる時間": "Actual travel time",
  "回": "×",
  "乗換": "Transfers",
  "円": "yen",
  "運賃": "Fare",
  "行き": "Outbound",
  "帰り": "Return",

  // ---- マイページ
  "ほかの画面へ": "Other pages",
  "プランをひらく": "Open plan",
  "{date} に保存": "Saved {date}",
  "中身を見る": "Show details",
  "削除": "Delete",
  "本当に消す": "Really delete",
  "保存したメイクの工程はまだありません。プランのメイクの工程で ☆ を押すと、ここに並びます。":
    "No saved makeup steps yet. Press ☆ on the makeup steps in your plan and they'll appear here.",
  "保存した動線はまだありません。プランの動線で、行き・帰りそれぞれの ☆ を押すと、ここに並びます。":
    "No saved routes yet. Press ☆ on the outbound or return route in your plan and they'll appear here.",
  "お気に入りから消しました。": "Deleted from favourites.",
  "お気に入りは{limit}件までです。マイページで要らないものを消してください":
    "You can keep up to {limit} favourites. Delete ones you don't need on My page.",

  // ---- ログイン・登録
  "メールでログイン": "Log in with email",
  "メールアドレス": "Email",
  "パスワード": "Password",
  "はじめて使う方は": "New here?",
  "アカウントを作る": "Create an account",
  "メールで登録": "Sign up with email",
  "パスワード（6文字以上）": "Password (6+ characters)",
  "パスワード（確認）": "Password (again)",
  "登録する": "Sign up",
  "アカウントを持っている方は": "Already have an account?",
  "確かめています…": "Checking…",
  "登録しています…": "Signing up…",
  "ログインの期限が切れました。もう一度入りなおしてください。": "Your session has expired. Please log in again.",
  "メールアドレスかパスワードが違います。": "Wrong email or password.",
  "このメールアドレスはもう登録されています。下の「ログイン」から入ってください。":
    "This email is already registered. Use “Log in” below.",
  "メールアドレスの形になっていません。": "That doesn't look like an email address.",
  "パスワードを入れてください。": "Enter your password.",
  "6文字以上にしてください。": "Use at least 6 characters.",
  "続けて失敗したので、少し時間をおいてからもう一度試してください。":
    "Too many failed attempts. Please wait a moment and try again.",
  "入ったあと、押した ☆ をお気に入りに保存します。": "Once you're in, we'll save the ☆ you pressed. ",
  "マイページとお気に入りは、ログインすると使えます。": "Log in to use My page and favourites. ",
  "組んだプランはそのまま引き継ぎます。": "Your plan carries over.",
  "メールアドレスを入れてください。": "Enter your email.",
  "上のパスワードと一致しません。": "Doesn't match the password above.",
  "ログインの相手（認証エミュレータ）に繋がりません。docker compose up api で起動しているか確かめてください。":
    "Can't reach the auth emulator. Check that it's running with docker compose up api.",
  "ログインの相手に繋がりません。通信の状態を確かめて、もう一度試してください。":
    "Can't reach the login service. Check your connection and try again.",
  "ログインできませんでした": "Couldn't log in",
};
