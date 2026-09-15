"""相談の条件を持ち、そろったらプランを組ませる。

「相談」ページの欄（イベント名・日付・目的地・開始・終了・作品名・キャラ名・出発駅・荷物）が
そのまま ChatSlots になる。自由文を読み取る入口は取り下げた。欄を埋めれば
読み違いが起きないので、聞き返しの会話を持つ理由がなくなった。
"""

from __future__ import annotations

from app.agents.orchestrator import Orchestrator, PlanError, PlanRequest
from app.domain.models import CharacterRef, ChatSession, ChatSlots, Layer, LuggageMode
from app.ports.repository import RepositoryPort


class ChatAgent:
    def __init__(self, orchestrator: Orchestrator, repository: RepositoryPort) -> None:
        self.orchestrator = orchestrator
        self.repository = repository

    async def history(self, layer: Layer) -> ChatSession:
        session = await self.repository.get_chat(layer.layer_id)
        if session is None:
            session = ChatSession(layer_id=layer.layer_id, lang=layer.lang)
            # 既定値として、プロフィールの荷物設定を先に埋めておく
            session.slots.luggage_mode = layer.prefs.luggage_mode
            await self.repository.save_chat(session)
        return session

    async def set_slots(self, layer: Layer, values: dict) -> ChatSession:
        """条件を書き換える。揃えばそのままプランを組む。空文字は「消す」として扱う。"""
        session = await self.history(layer)
        session.lang = layer.lang
        for name, value in values.items():
            if name in ChatSlots.model_fields:
                setattr(session.slots, name, value or None)
        # 保存する前に確かめる。組めない時刻を残すと、次に開いたときも同じ誤りで止まる
        slots = session.slots
        if slots.starts_time and slots.ends_time and slots.ends_time <= slots.starts_time:
            raise PlanError("終了は開始より後の時刻にしてください。", "ends_time", "ends_before_starts")

        if session.slots.is_complete:
            session.exp_id = await self._build_plan(layer, session.slots)
        return await self.repository.save_chat(session)

    async def _build_plan(self, layer: Layer, slots: ChatSlots) -> str:
        req = PlanRequest(
            layer_id=layer.layer_id,
            event_name=slots.event_name,
            event_id=slots.event_id,
            destination_station=slots.destination_station,
            starts_time=slots.starts_time,
            ends_time=slots.ends_time,
            day=slots.day,
            character=CharacterRef(title=slots.title, name=slots.character),
            origin_station=slots.origin_station,
            luggage_mode=slots.luggage_mode or LuggageMode.CARRY,
            lang=layer.lang,
        )
        exp, _extras = await self.orchestrator.plan(req)
        return exp.exp_id
