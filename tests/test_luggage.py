"""大荷物動線の検証。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain import luggage
from app.domain.models import (
    LuggageMode,
    RouteSegment,
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
