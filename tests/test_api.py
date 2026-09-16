"""API の結合テスト。ユースケース（設計書 §3）をそのままなぞる。"""

from __future__ import annotations

from datetime import datetime

from tests.conftest import DAY


def _has_japanese(text: str) -> bool:
    """仮名と漢字の両方を見る（色名の混入は漢字1文字で起きる）。"""
    return any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)


def _dt(value: str) -> datetime:
    """API は末尾 Z で返すので、比較は datetime に戻してから行う。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _plan(session, **overrides) -> dict:
    body = {
        "event_id": "comiket",
        "day": DAY.isoformat(),
        "character": {"title": "作品A", "name": "キャラB"},
        "origin_station": "横浜",
        "luggage_mode": "heavy",
    }
    body.update(overrides)
    res = session.post("/api/expeditions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------- 基本


def test_health_reports_providers(client):
    res = client.get("/health")
    assert res.status_code == 200
    providers = res.json()["providers"]
    # キーは環境変数と同じ名前、値はその変数の実効値（EKISPERT_MODE=mock で動いている）
    assert providers["ekispert"] == "ekispert:mock"
    assert providers["gemini"] == "gemini:stub"
    assert providers["auth"] == "auth:dev"


def test_events_master_is_served(client):
    ids = {e["event_id"] for e in client.get("/api/events").json()["events"]}
    assert ids == {"wcs", "acosta", "comiket", "hokokos"}


def test_event_names_are_matched_for_autofill(client):
    """相談の画面は、これで目的地と時刻を自動で埋める。略称も当たる。"""
    event = client.get("/api/events/match", params={"name": "コミケ"}).json()["event"]
    assert event["event_id"] == "comiket"
    assert event["defaults"] == {"destination_station": "国際展示場", "starts_time": "10:00", "ends_time": "16:00"}
    assert client.get("/api/events/match", params={"name": "地元の撮影会"}).json() == {"event": None}


def test_station_candidates_need_a_session(client, guest):
    """入力のたびに駅すぱあとを呼ぶので、通行証の無い呼び出しには答えない。"""
    assert client.get("/api/stations", params={"name": "国際"}).status_code == 401
    assert guest.get("/api/stations", params={"name": "国際"}).json() == {"stations": ["国際展示場"]}


def test_expedition_can_be_planned_for_a_local_event(user):
    body = _plan(
        user,
        event_id=None,
        event_name="地元の撮影会",
        destination_station="大宮",
        starts_time="13:00",
        ends_time="17:00",
    )
    assert body["event"]["name"] == "地元の撮影会"
    assert body["routes"]["outbound"]["segments"][-1]["to_station"] == "大宮"


def test_local_event_without_a_destination_is_refused(user):
    res = user.post(
        "/api/expeditions",
        json={
            "event_name": "地元の撮影会",
            "starts_time": "13:00",
            "ends_time": "17:00",
            "day": DAY.isoformat(),
            "character": {"title": "作品A", "name": "キャラB"},
            "origin_station": "横浜",
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "destination_station"


# ---------------------------------------------------------------- 認証


def test_protected_endpoints_require_a_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/chat").status_code == 401
    assert client.post("/api/expeditions", json={}).status_code == 401


def test_tampered_token_is_rejected(client, user):
    bad = {"Authorization": user.headers["Authorization"] + "x"}
    assert client.get("/api/me", headers=bad).status_code == 401


def test_same_user_returns_the_same_account(client, login):
    first = login("同じ人")
    second = login("同じ人")
    assert first.layer_id == second.layer_id


def test_account_stores_no_personal_data(user):
    me = user.get("/api/me").json()
    assert me["auth_uid"]  # 認証IDだけを持つ
    # 名前も持たない。表示名があると、コス名から素性へ辿る手がかりになる
    assert "handle" not in me
    assert "email" not in me
    logs = user.get("/api/audit", params={"subject_id": user.layer_id}).json()["logs"]
    linked = [log for log in logs if log["action"] == "account_linked"]
    assert linked and linked[0]["payload"]["stores_email"] is False


def test_test_login_config_declares_itself(client):
    config = client.get("/api/auth/config").json()
    assert config["provider"] == "dev"
    assert "パスワード検証なし" in config["warning"]


# ---------------------------------------------------------------- 遠征


def test_solo_expedition_plan_covers_the_whole_day(user):
    """ユースケース1（ソロ遠征）: メイク→動線が一度に揃う。"""
    body = _plan(user)

    assert body["makeup"]["steps"], "メイク工程が空"
    outbound = body["routes"]["outbound"]
    assert outbound["segments"], "経路が空"
    # 大荷物ぶんは乗換の回数にだけ乗る（乗換ゼロなら伸びない）
    assert outbound["effective_minutes"] >= outbound["base_minutes"]
    assert outbound["transfers"] == max(len(outbound["segments"]) - 1, 0)
    assert "dressing" not in body  # 更衣室の予測は取り下げた
    # 行きは開場までに着き、帰りは閉場のあとに出る
    assert _dt(outbound["arrive_at"]) <= _dt(body["event"]["starts_at"])
    assert _dt(body["routes"]["return"]["depart_at"]) >= _dt(body["event"]["ends_at"])
    assert body["extras"]["wake_up_hint"]

    # 設計書 §7-4: キャラ情報は外向き応答に出さない
    assert "character" not in body


def test_expedition_is_not_readable_by_others(user, login):
    exp = _plan(user)
    stranger = login("別の人")
    assert stranger.get(f"/api/expeditions/{exp['exp_id']}").status_code == 403


def test_english_layer_gets_english_plan(login):
    """ユースケース3（訪日レイヤー）: 母語で工程と案内が返る。"""
    visitor = login("Visitor")
    visitor.patch("/api/me", json={"lang": "en"})
    body = _plan(
        visitor,
        event_id="wcs",
        character={"title": "Series A", "name": "Character B"},
        origin_station="名古屋",
    )
    joined = " ".join(s["instruction"] for s in body["makeup"]["steps"])
    assert not _has_japanese(joined), joined
    assert body["extras"]["ui"]["route.heading"] == "Route (heavy-luggage mode)"
    # 経路の注意書きと工程の見出しも英語（駅名は固有名詞なので問わない）
    warnings = [w for r in body["routes"].values() for w in r["warnings"]]
    assert not any(_has_japanese(w) for w in warnings), warnings
    assert not any(_has_japanese(s["area_label"]) for s in body["makeup"]["steps"])


def test_switching_language_rebuilds_the_plan_in_that_language(user):
    """画面の言語を変えたら、プランの文面もその言語で組み直す。"""
    from tests.test_ask import FULL

    before = user.patch("/api/chat/slots", json=FULL).json()["expedition"]
    assert _has_japanese(before["makeup"]["steps"][0]["instruction"])

    user.patch("/api/me", json={"lang": "en"})
    chat = user.get("/api/chat").json()
    after = user.get(f"/api/expeditions/{chat['exp_id']}").json()
    assert after["lang"] == "en"
    assert not _has_japanese(" ".join(s["instruction"] for s in after["makeup"]["steps"]))


def test_errors_carry_a_code_the_screen_can_translate(user):
    """画面は code を見て、自分の言語で言い直す（サーバの文面は日本語のまま）。"""
    from tests.test_ask import LOCAL

    user.patch("/api/chat/slots", json=LOCAL)
    detail = user.patch("/api/chat/slots", json={"starts_time": "18:00"}).json()["detail"]
    assert (detail["field"], detail["code"]) == ("ends_time", "ends_before_starts")

