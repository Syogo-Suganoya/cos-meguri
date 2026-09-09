"""大荷物動線と更衣室混雑予測の検証。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain import crowd, luggage
from app.domain.events import get_event
from app.domain.models import (
    JST,
    CrowdLevel,
    LuggageMode,
    RouteSegment,
    ServiceDisruption,
)

DAY = datetime(2026, 8, 15, tzinfo=timezone.utc)

EV_ROUTE = [
    RouteSegment(from_station="A", to_station="B", line="JR線", minutes=20, fare_yen=200),
    RouteSegment(from_station="B", to_station="C", line="地下鉄", minutes=10, fare_yen=180),
]
DIRECT_ROUTE = [
    RouteSegment(from_station="A", to_station="C", line="直通", minutes=32, fare_yen=320),
]


def test_heavy_luggage_costs_more_than_light():
    light = luggage.effective_minutes(EV_ROUTE, LuggageMode.LIGHT)
    heavy = luggage.effective_minutes(EV_ROUTE, LuggageMode.HEAVY)
    assert light == 30
    assert heavy > light


def test_direct_route_wins_when_the_transfer_penalty_outweighs_the_ride():
    """乗換1回ぶんの負担（+8分）が所要差（2分）を上回るので、直通を選ぶ。

    駅設備（EV・階段）は駅すぱあと API に無いので優劣の軸に使わない。
    """
    plans = [
        luggage.build_plan(EV_ROUTE, direction="outbound", mode=LuggageMode.HEAVY),
        luggage.build_plan(DIRECT_ROUTE, direction="outbound", mode=LuggageMode.HEAVY),
    ]
    assert luggage.prefer_easiest(plans)[0].segments == DIRECT_ROUTE


def test_a_transfer_is_still_worth_it_when_it_saves_enough_time():
    """乗換の少なさを絶対視しない。直通が遅すぎれば乗換ありを選ぶ。"""
    slow_direct = [
        RouteSegment(from_station="A", to_station="C", line="各停", minutes=60, fare_yen=300)
    ]
    plans = [
        luggage.build_plan(EV_ROUTE, direction="outbound", mode=LuggageMode.HEAVY),
        luggage.build_plan(slow_direct, direction="outbound", mode=LuggageMode.HEAVY),
    ]
    best = luggage.prefer_easiest(plans)[0]
    assert best.segments == EV_ROUTE
    assert best.transfers == 1


def test_arrive_by_backsolves_departure_including_penalty():
    arrive = DAY.replace(hour=10)
    plan = luggage.build_plan(
        EV_ROUTE, direction="outbound", mode=LuggageMode.HEAVY, arrive_by=arrive
    )
    assert plan.arrive_at == arrive
    assert plan.depart_at == arrive - timedelta(minutes=plan.effective_minutes)
    assert plan.penalty_minutes > 0


def test_disruption_pulls_departure_earlier():
    arrive = DAY.replace(hour=10)
    plan = luggage.build_plan(
        EV_ROUTE, direction="outbound", mode=LuggageMode.CARRY, arrive_by=arrive
    )
    updated, delay = luggage.apply_disruptions(
        plan,
        [ServiceDisruption(line="JR線", status="遅延", delay_minutes=15, detail="人身事故")],
    )
    assert delay == 15
    assert updated.depart_at < plan.depart_at
    assert any("JR線" in w for w in updated.warnings)


def test_unrelated_disruption_is_ignored():
    plan = luggage.build_plan(EV_ROUTE, direction="outbound", mode=LuggageMode.CARRY)
    updated, delay = luggage.apply_disruptions(
        plan, [ServiceDisruption(line="無関係線", status="遅延", delay_minutes=30, detail="")]
    )
    assert delay == 0
    assert updated is plan


def test_crowd_has_two_peaks_and_recommends_off_peak():
    event = get_event("comiket")
    plan = crowd.build_plan(event, DAY)
    assert plan.is_model_estimate is True
    assert plan.slots

    peak_slots = [s for s in plan.slots if s.level is CrowdLevel.PEAK]
    entry = next(s for s in plan.slots if s.starts_at == plan.recommended_entry)
    assert plan.recommended_entry and plan.recommended_exit
    assert plan.recommended_entry < plan.recommended_exit
    if peak_slots:
        assert entry.wait_minutes <= min(s.wait_minutes for s in peak_slots)


def test_teardown_alert_precedes_recommended_exit():
    plan = crowd.build_plan(get_event("acosta"), DAY)
    assert plan.teardown_alert_at == plan.recommended_exit - timedelta(minutes=30)


def test_slots_follow_venue_local_hours():
    """開場時刻は JST 基準。UTC で日付を渡しても会場の時刻がずれない。"""
    event = get_event("comiket")  # 10:00-16:00 JST
    plan = crowd.build_plan(event, DAY)  # DAY は UTC 0 時
    first = plan.slots[0].starts_at.astimezone(JST)
    last = plan.slots[-1].starts_at.astimezone(JST)
    assert first.hour == event.opens_at_hour
    assert first.date() == DAY.date()
    assert last.hour < event.closes_at_hour


def test_bigger_event_means_longer_waits():
    mega = crowd.build_plan(get_event("comiket"), DAY)
    medium = crowd.build_plan(get_event("hokokos"), DAY)
    assert max(s.wait_minutes for s in mega.slots) > max(
        s.wait_minutes for s in medium.slots
    )
