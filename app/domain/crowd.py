"""更衣室の混雑予測（設計書 §4 更衣室エージェント）。

MVP は実データ非連携で、イベント規模・更衣室の収容・開閉時刻からの
モデル値を出す（設計書 §9「MVPで捨てるもの」）。実測値ではないことは
DressingPlan.is_model_estimate で常に明示し、UI にも出す。

需要曲線は 2 つの山の混合:
- 入場ピーク: 開場直後（着替えて撮影に出たい）
- 撤収ピーク: 閉場前（撤収と帰路が重なる）
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.domain.models import (
    CrowdLevel,
    DressingPlan,
    DressingSlot,
    EventMaster,
    event_day,
)

SLOT_MINUTES = 30
# 1人あたりの更衣室占有時間（分）。スループット換算に使う。
OCCUPANCY_MINUTES = 20


def _bell(x: float, center: float, width: float) -> float:
    return math.exp(-((x - center) ** 2) / (2 * width**2))


def demand_weights(slot_count: int) -> list[float]:
    """スロットごとの需要ウェイト（合計1.0に正規化）。"""
    if slot_count <= 0:
        return []
    entry_center = slot_count * 0.12
    exit_center = slot_count * 0.86
    width = max(slot_count * 0.11, 1.0)

    raw = [
        _bell(i, entry_center, width) * 1.0 + _bell(i, exit_center, width) * 0.75 + 0.06
        for i in range(slot_count)
    ]
    total = sum(raw)
    return [v / total for v in raw]


def slot_throughput(event: EventMaster) -> int:
    """1スロットで捌ける人数 = 同時収容 × 回転数 × 部屋数。"""
    turns = SLOT_MINUTES / OCCUPANCY_MINUTES
    return int(event.dressing_rooms * event.dressing_capacity * turns)


def _wait_minutes(demand: int, throughput: int) -> int:
    """需要が捌ける量を超えた分だけ待ち行列が伸びる、という単純モデル。"""
    if throughput <= 0:
        return 999
    excess = demand - throughput
    if excess <= 0:
        return max(0, int(SLOT_MINUTES * (demand / throughput) * 0.15))
    return int(SLOT_MINUTES * (excess / throughput)) + 5


def _level(occupancy: float) -> CrowdLevel:
    if occupancy < 0.7:
        return CrowdLevel.CALM
    if occupancy < 1.0:
        return CrowdLevel.BUSY
    return CrowdLevel.PEAK


def predict(
    event: EventMaster,
    day: datetime,
    *,
    attendance_factor: float = 1.0,
) -> list[DressingSlot]:
    """当日の 30 分刻み予測を返す。attendance_factor で規模を補正できる。"""
    base = event_day(day)  # 開場時刻は JST 基準
    opens = base.replace(hour=event.opens_at_hour)
    closes = base.replace(hour=event.closes_at_hour)
    total_minutes = int((closes - opens).total_seconds() // 60)
    slot_count = max(total_minutes // SLOT_MINUTES, 1)

    weights = demand_weights(slot_count)
    population = int(event.expected_cosplayers * attendance_factor)
    throughput = slot_throughput(event)

    slots: list[DressingSlot] = []
    for i, w in enumerate(weights):
        # 入退場で2回使うため、延べ利用回数は人数の約2倍
        demand = int(population * 2 * w)
        occupancy = demand / throughput if throughput else 9.9
        slots.append(
            DressingSlot(
                starts_at=opens + timedelta(minutes=i * SLOT_MINUTES),
                predicted_users=demand,
                capacity=throughput,
                occupancy=round(occupancy, 2),
                wait_minutes=_wait_minutes(demand, throughput),
                level=_level(occupancy),
            )
        )
    return slots


def build_plan(
    event: EventMaster,
    day: datetime,
    *,
    arrive_at: datetime | None = None,
    leave_by: datetime | None = None,
    attendance_factor: float = 1.0,
) -> DressingPlan:
    """入場・撤収の推奨タイミングまで含めた行動プランを組む。"""
    slots = predict(event, day, attendance_factor=attendance_factor)
    if not slots:
        return DressingPlan(event_id=event.event_id, rationale="スロットを算出できませんでした")

    midpoint = slots[len(slots) // 2].starts_at

    entry_pool = [s for s in slots if s.starts_at < midpoint]
    if arrive_at:
        feasible = [s for s in entry_pool if s.starts_at >= arrive_at]
        entry_pool = feasible or entry_pool
    entry = min(entry_pool, key=lambda s: (s.wait_minutes, s.starts_at), default=slots[0])

    exit_pool = [s for s in slots if s.starts_at >= midpoint]
    if leave_by:
        feasible = [s for s in exit_pool if s.starts_at <= leave_by]
        exit_pool = feasible or exit_pool
    exit_slot = min(
        exit_pool, key=lambda s: (s.wait_minutes, s.starts_at), default=slots[-1]
    )

    peak = max(slots, key=lambda s: s.occupancy)
    rationale = (
        f"{event.name}の規模（想定{int(event.expected_cosplayers * attendance_factor):,}人）と"
        f"更衣室{event.dressing_rooms}室×{event.dressing_capacity}人から算出したモデル値です。"
        f"ピークは{peak.starts_at:%H:%M}（待ち約{peak.wait_minutes}分）。"
        f"入場は{entry.starts_at:%H:%M}（待ち約{entry.wait_minutes}分）、"
        f"撤収は{exit_slot.starts_at:%H:%M}（待ち約{exit_slot.wait_minutes}分）を推奨します。"
    )

    return DressingPlan(
        event_id=event.event_id,
        slots=slots,
        recommended_entry=entry.starts_at,
        recommended_exit=exit_slot.starts_at,
        teardown_alert_at=exit_slot.starts_at - timedelta(minutes=30),
        rationale=rationale,
        is_model_estimate=True,
    )
