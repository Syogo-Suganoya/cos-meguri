"""スケジューラから叩くバッチ用エンドポイントの検証。

PWA を公開するためサービス全体が未認証許可になるので、この2本だけは
アプリ側の共有シークレットで守る。設定漏れのときは開いたままにせず閉じる。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.adapters.registry import get_adapters
from app.api.deps import get_agents
from app.config import get_settings
from tests.conftest import DAY

TASK_PATHS = ["/api/tasks/purge", "/api/tasks/day-of"]


@pytest.fixture
def secured(client):
    """TASKS_TOKEN を設定した状態にする。"""
    settings = get_settings()
    original = settings.tasks_token
    settings.tasks_token = "test-token"
    yield client
    settings.tasks_token = original


@pytest.fixture
def production(client):
    """本番相当（ローカルではない）かつ TASKS_TOKEN 未設定。

    アダプタは先に組み立てておく。稼働中のサービスは起動時に構成済みで、
    本番で開発用ログインのまま起動することは registry 側が阻止している。
    """
    get_adapters()
    settings = get_settings()
    original_env, original_token = settings.app_env, settings.tasks_token
    settings.app_env, settings.tasks_token = "production", ""
    yield client
    settings.app_env, settings.tasks_token = original_env, original_token


def _plan(session, **overrides) -> dict:
    body = {
        "event_id": "acosta",
        "day": DAY.isoformat(),
        "character": {"title": "作品A", "name": "キャラB"},
        "origin_station": "新宿",
    }
    body.update(overrides)
    res = session.post("/api/expeditions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------- 保護


@pytest.mark.parametrize("path", TASK_PATHS)
def test_token_is_required_once_configured(secured, path):
    assert secured.post(path).status_code == 403
    assert secured.post(path, headers={"X-Tasks-Token": "wrong"}).status_code == 403
    assert secured.post(path, headers={"X-Tasks-Token": "test-token"}).status_code == 200


@pytest.mark.parametrize("path", TASK_PATHS)
def test_endpoints_close_when_token_is_missing_outside_local(production, path):
    """未設定のまま本番に出ても、開いたままにはしない。"""
    res = production.post(path)
    assert res.status_code == 503
    assert "TASKS_TOKEN" in res.json()["detail"]


@pytest.mark.parametrize("path", TASK_PATHS)
def test_local_works_without_a_token(client, path):
    """ローカル開発では設定なしで叩ける。"""
    assert client.post(path).status_code == 200


# ---------------------------------------------------------------- 当日バッチ


def test_batch_advances_only_expeditions_held_that_day(user, secured):
    """その日の遠征だけを進める。別の日のものには触れない。"""
    today = _plan(user)
    other_day = _plan(user, day=(DAY + timedelta(days=3)).isoformat())

    alert_at = datetime.fromisoformat(
        today["dressing"]["teardown_alert_at"].replace("Z", "+00:00")
    )
    res = secured.post(
        "/api/tasks/day-of",
        params={"now": (alert_at + timedelta(minutes=5)).isoformat()},
        headers={"X-Tasks-Token": "test-token"},
    ).json()

    assert res["processed"] == 1
    assert res["expeditions"][0]["exp_id"] == today["exp_id"]
    assert res["expeditions"][0]["dressing_alert"] is True
    assert other_day["exp_id"] not in [e["exp_id"] for e in res["expeditions"]]


def test_batch_delivers_alerts_to_each_owner(login, secured):
    """他人の遠征も1回のバッチで進み、通知はそれぞれの持ち主に届く。"""
    a, b = login("Aさん"), login("Bさん")
    exp_a = _plan(a)
    _plan(b)

    alert_at = datetime.fromisoformat(
        exp_a["dressing"]["teardown_alert_at"].replace("Z", "+00:00")
    )
    res = secured.post(
        "/api/tasks/day-of",
        params={"now": (alert_at + timedelta(minutes=5)).isoformat()},
        headers={"X-Tasks-Token": "test-token"},
    ).json()

    assert res["processed"] == 2
    for session in (a, b):
        inbox = session.get("/api/me/notifications").json()["notifications"]
        assert any(n["kind"] == "teardown" for n in inbox)


def test_batch_is_quiet_before_the_alert_time(user, secured):
    """アラート時刻の前は何も通知しない（無用な通知を飛ばさない）。"""
    _plan(user)
    res = secured.post(
        "/api/tasks/day-of",
        params={"now": DAY.replace(hour=0).isoformat()},
        headers={"X-Tasks-Token": "test-token"},
    ).json()
    assert res["processed"] == 1
    assert res["notified"] == 0


def test_batch_survives_a_broken_expedition(user, secured, monkeypatch):
    """1件が落ちても残りを進める。"""
    _plan(user)
    _plan(user, origin_station="横浜")

    agents = get_agents()
    original = agents.orchestrator.run_day_of
    calls = {"n": 0}

    async def flaky(exp_id, *, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await original(exp_id, now=now)

    monkeypatch.setattr(agents.orchestrator, "run_day_of", flaky)
    res = secured.post(
        "/api/tasks/day-of",
        params={"now": DAY.isoformat()},
        headers={"X-Tasks-Token": "test-token"},
    ).json()

    assert calls["n"] == 2  # 2件とも試みる
    assert res["processed"] == 1  # 成功したぶんだけ返る


# ---------------------------------------------------------------- healthz


def test_healthz_warns_about_dev_login(client):
    warnings = client.get("/healthz").json()["warnings"]
    assert any("開発用ログイン" in w for w in warnings)


def test_healthz_warns_when_live_fell_back_to_mock(client):
    settings = get_settings()
    original = settings.llm_mode
    settings.llm_mode = "live"  # キーは無いので mock に落ちる
    get_adapters.cache_clear()
    get_agents.cache_clear()
    try:
        warnings = client.get("/healthz").json()["warnings"]
        assert any("llm: live 指定ですが" in w for w in warnings)
    finally:
        settings.llm_mode = original
        get_adapters.cache_clear()
        get_agents.cache_clear()


def test_healthz_warns_when_tasks_token_is_missing(production):
    warnings = production.get("/healthz").json()["warnings"]
    assert any("TASKS_TOKEN" in w for w in warnings)
