"""API の結合テスト。ユースケース（設計書 §3）をそのままなぞる。"""

from __future__ import annotations

from datetime import datetime, timedelta

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


def test_healthz_reports_providers(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    providers = res.json()["providers"]
    # キーは環境変数と同じ名前、値はその変数の実効値（EKISPERT_MODE=mock で動いている）
    assert providers["ekispert"] == "ekispert:mock"
    assert providers["gemini"] == "gemini:stub"
    assert providers["notifier"] == "notifier:in_app"
    assert providers["auth"] == "auth:dev"


def test_events_master_is_served(client):
    ids = {e["event_id"] for e in client.get("/api/events").json()["events"]}
    assert ids == {"wcs", "acosta", "comiket", "hokokos"}


# ---------------------------------------------------------------- 認証


def test_protected_endpoints_require_a_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/chat").status_code == 401
    assert client.post("/api/expeditions", json={}).status_code == 401


def test_tampered_token_is_rejected(client, user):
    bad = {"Authorization": user.headers["Authorization"] + "x"}
    assert client.get("/api/me", headers=bad).status_code == 401


def test_same_handle_returns_the_same_account(client, login):
    first = login("同じ人")
    second = login("同じ人")
    assert first.layer_id == second.layer_id


def test_account_stores_no_personal_data(user):
    me = user.get("/api/me").json()
    assert me["handle"] == "テストレイヤー"
    assert me["auth_uid"]  # 認証IDだけを持つ
    assert "email" not in me
    logs = user.get("/api/audit", params={"subject_id": user.layer_id}).json()["logs"]
    linked = [log for log in logs if log["action"] == "account_linked"]
    assert linked and linked[0]["payload"]["stores_email"] is False


def test_dev_login_config_declares_itself(client):
    config = client.get("/api/auth/config").json()
    assert config["provider"] == "dev"
    assert config["dev_login"] is True
    assert "パスワード検証なし" in config["warning"]


# ---------------------------------------------------------------- 遠征


def test_solo_expedition_plan_covers_the_whole_day(user):
    """ユースケース1（ソロ遠征）: メイク→動線→更衣室が一度に揃う。"""
    body = _plan(user)

    assert body["makeup"]["steps"], "メイク工程が空"
    outbound = body["routes"]["outbound"]
    assert outbound["segments"], "経路が空"
    # 大荷物ぶんは乗換の回数にだけ乗る（乗換ゼロなら伸びない）
    assert outbound["effective_minutes"] >= outbound["base_minutes"]
    assert outbound["transfers"] == max(len(outbound["segments"]) - 1, 0)
    assert body["dressing"]["is_model_estimate"] is True
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
    assert body["extras"]["ui"]["dressing.heading"] == "Changing-room forecast"


# ---------------------------------------------------------------- 当日モード・お知らせ


def test_day_of_alert_lands_in_the_in_app_inbox(user):
    """当日モードの自律通知が、外部サービスではなくアプリ内お知らせに積まれる。"""
    exp = _plan(user, event_id="acosta")
    alert_at = _dt(exp["dressing"]["teardown_alert_at"])

    res = user.post(
        f"/api/expeditions/{exp['exp_id']}/day-of",
        params={"now": (alert_at + timedelta(minutes=5)).isoformat()},
    )
    assert res.status_code == 200
    assert res.json()["dressing_alert"]
    assert res.json()["notified"] >= 1

    inbox = user.get("/api/me/notifications").json()
    assert inbox["unread"] >= 1
    assert any(n["kind"] == "teardown" for n in inbox["notifications"])


def test_notifications_can_be_marked_read(user):
    exp = _plan(user, event_id="acosta")
    alert_at = _dt(exp["dressing"]["teardown_alert_at"])
    user.post(
        f"/api/expeditions/{exp['exp_id']}/day-of",
        params={"now": (alert_at + timedelta(minutes=5)).isoformat()},
    )

    assert user.post("/api/me/notifications/read", json={}).json()["read"] >= 1
    assert user.get("/api/me/notifications").json()["unread"] == 0


def test_inbox_is_private_to_its_owner(user, login):
    exp = _plan(user, event_id="acosta")
    alert_at = _dt(exp["dressing"]["teardown_alert_at"])
    user.post(
        f"/api/expeditions/{exp['exp_id']}/day-of",
        params={"now": (alert_at + timedelta(minutes=5)).isoformat()},
    )
    stranger = login("無関係な人")
    assert stranger.get("/api/me/notifications").json()["notifications"] == []


# ---------------------------------------------------------------- 合わせ


def test_awase_flow_requires_organizer_approval(user, login):
    """ユースケース2（合わせ）: 招集→進捗→監視→承認まで通す。"""
    organizer = user
    awase = organizer.post(
        "/api/awase",
        json={
            "title": "合わせテスト",
            "event_id": "acosta",
            "day": DAY.isoformat(),
            "members": [{"handle": "Aさん"}],
        },
    ).json()
    awase_id = awase["awase_id"]
    assert awase["summary"]["total"] == 2
    late_id = next(m["layer_id"] for m in awase["members"] if not m["is_organizer"])

    shoot_at = DAY.replace(hour=13)
    organizer.post(
        f"/api/awase/{awase_id}/shoots",
        json={"starts_at": shoot_at.isoformat(), "place": "屋上", "minutes": 30},
    )

    # 主催者が代理で、遅れそうなメンバーの ETA を入れる
    organizer.post(
        f"/api/awase/{awase_id}/progress",
        json={
            "layer_id": late_id,
            "progress": "en_route",
            "eta": shoot_at.replace(minute=35).isoformat(),
            "share_location": True,
        },
    )

    monitored = organizer.post(
        f"/api/awase/{awase_id}/monitor",
        params={"now": DAY.replace(hour=12).isoformat()},
    ).json()
    assert len(monitored["proposals"]) == 1
    proposal = monitored["proposals"][0]
    # 起案しただけで枠は動かない
    assert _dt(monitored["awase"]["shoots"][0]["starts_at"]) == shoot_at

    # 承認依頼は主催者のお知らせに届く
    inbox = organizer.get("/api/me/notifications").json()["notifications"]
    assert any(n["kind"] == "reschedule_request" for n in inbox)

    approved = organizer.post(
        f"/api/awase/{awase_id}/proposals/{proposal['proposal_id']}/decision",
        json={"approved": True},
    ).json()
    assert approved["proposal"]["status"] == "approved"
    assert approved["awase"]["shoots"][0]["starts_at"] == proposal["proposed_start"]

    logs = organizer.get("/api/audit", params={"subject_id": awase_id}).json()["logs"]
    assert any(log["action"] == "reschedule_approved" for log in logs)
    assert any(log["action"] == "location_share_enabled" for log in logs)


def test_notification_text_uses_venue_local_time(user):
    """お知らせの文面は会場時刻（JST）で書く。

    撮影枠はクライアントから UTC で届くので、素直に書式化すると9時間ずれる。
    """
    awase = user.post(
        "/api/awase",
        json={"title": "時刻テスト", "event_id": "acosta", "day": DAY.isoformat(),
              "members": [{"handle": "Cさん"}]},
    ).json()
    awase_id = awase["awase_id"]
    late_id = next(m["layer_id"] for m in awase["members"] if not m["is_organizer"])

    # 13:00 JST = 04:00 UTC の撮影枠
    shoot_at = DAY.replace(hour=4)
    user.post(
        f"/api/awase/{awase_id}/shoots",
        json={"starts_at": shoot_at.isoformat(), "place": "屋上"},
    )
    user.post(
        f"/api/awase/{awase_id}/progress",
        json={
            "layer_id": late_id,
            "progress": "en_route",
            "eta": shoot_at.replace(minute=35).isoformat(),
            "share_location": True,
        },
    )
    user.post(
        f"/api/awase/{awase_id}/monitor",
        params={"now": DAY.replace(hour=3).isoformat()},
    )

    request = next(
        n
        for n in user.get("/api/me/notifications").json()["notifications"]
        if n["kind"] == "reschedule_request"
    )
    assert "13:00" in request["message"], request["message"]
    assert "04:00" not in request["message"]


def test_invited_member_takes_over_the_pending_account(user, login):
    """招待だけされた相手が、同じコス名でログインするとアカウントを引き継ぐ。"""
    awase = user.post(
        "/api/awase",
        json={
            "title": "引き継ぎテスト",
            "event_id": "acosta",
            "day": DAY.isoformat(),
            "members": [{"handle": "あとから来る人"}],
        },
    ).json()
    invited_id = next(m["layer_id"] for m in awase["members"] if not m["is_organizer"])

    member = login("あとから来る人")
    assert member.layer_id == invited_id
    assert member.get(f"/api/awase/{awase['awase_id']}").status_code == 200

    inbox = member.get("/api/me/notifications").json()["notifications"]
    assert any(n["kind"] == "awase_invite" for n in inbox)


def test_non_organizer_cannot_confirm_or_add_shoots(user, login):
    awase = user.post(
        "/api/awase",
        json={
            "title": "権限テスト",
            "event_id": "acosta",
            "day": DAY.isoformat(),
            "members": [{"handle": "Bさん"}],
        },
    ).json()
    awase_id = awase["awase_id"]
    shoot_at = DAY.replace(hour=13)
    user.post(
        f"/api/awase/{awase_id}/shoots",
        json={"starts_at": shoot_at.isoformat(), "place": "屋上"},
    )
    late_id = next(m["layer_id"] for m in awase["members"] if not m["is_organizer"])
    user.post(
        f"/api/awase/{awase_id}/progress",
        json={
            "layer_id": late_id,
            "progress": "en_route",
            "eta": shoot_at.replace(minute=35).isoformat(),
            "share_location": True,
        },
    )
    proposal = user.post(
        f"/api/awase/{awase_id}/monitor", params={"now": DAY.replace(hour=12).isoformat()}
    ).json()["proposals"][0]

    member = login("Bさん")
    assert (
        member.post(
            f"/api/awase/{awase_id}/proposals/{proposal['proposal_id']}/decision",
            json={"approved": True},
        ).status_code
        == 403
    )
    assert (
        member.post(
            f"/api/awase/{awase_id}/shoots", json={"starts_at": shoot_at.isoformat()}
        ).status_code
        == 403
    )
    # 他人の進捗も動かせない
    assert (
        member.post(
            f"/api/awase/{awase_id}/progress",
            json={"layer_id": user.layer_id, "progress": "arrived"},
        ).status_code
        == 403
    )


def test_outsider_cannot_read_an_awase(user, login):
    awase = user.post(
        "/api/awase",
        json={"title": "非公開", "event_id": "acosta", "day": DAY.isoformat()},
    ).json()
    stranger = login("部外者")
    assert stranger.get(f"/api/awase/{awase['awase_id']}").status_code == 403
