"""更衣室エージェント（設計書 §4）。自律性は「推奨まで」。

MVP は実データ非連携なので、出す値がモデル推定であることを
文面にも構造にも残す（is_model_estimate と rationale の両方）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain import crowd
from app.domain.models import CrowdLevel, DressingPlan, EventMaster, jst_hm
from app.ports.llm import LlmPort


class DressingAgent:
    def __init__(self, llm: LlmPort) -> None:
        self.llm = llm

    async def plan(
        self,
        event: EventMaster,
        day: datetime,
        *,
        arrive_at: datetime | None = None,
        leave_by: datetime | None = None,
        attendance_factor: float = 1.0,
    ) -> DressingPlan:
        plan = crowd.build_plan(
            event,
            day,
            arrive_at=arrive_at,
            leave_by=leave_by,
            attendance_factor=attendance_factor,
        )
        plan.rationale = await self.llm.explain(
            "コスプレイヤー向けに、更衣室の混雑予測と推奨タイミングを2文で伝えてください。"
            f"根拠: {plan.rationale}",
            fallback=plan.rationale,
        )
        return plan

    def teardown_alert(self, plan: DressingPlan) -> str | None:
        """撤収アラートの文面。推奨撤収の30分前に飛ばす想定。"""
        if not plan.recommended_exit:
            return None
        return (
            f"撤収の目安は{jst_hm(plan.recommended_exit)}です。"
            "この後は更衣室と帰路が同時に混みます。着替えの列に並ぶなら今が最後の余裕です。"
        )

    def peak_windows(self, plan: DressingPlan) -> list[dict]:
        """ピーク帯だけを抜き出す。UI の警告表示用。"""
        return [
            {
                "starts_at": s.starts_at.isoformat(),
                "wait_minutes": s.wait_minutes,
                "occupancy": s.occupancy,
            }
            for s in plan.slots
            if s.level is CrowdLevel.PEAK
        ]

    def next_alert_at(self, plan: DressingPlan) -> datetime | None:
        """次のアラート時刻。当日モードを進めたときに、過ぎていれば知らせる。"""
        if plan.teardown_alert_at:
            return plan.teardown_alert_at
        if plan.recommended_exit:
            return plan.recommended_exit - timedelta(minutes=30)
        return None
