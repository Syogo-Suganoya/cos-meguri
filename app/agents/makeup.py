"""メイクナビエージェント（設計書 §4）。手順生成は自律。

骨格は domain/makeup.py のルールで決め切り、Gemini は
「キャラ像の補完」と「母語への言い換え」だけを担当する。
LLM が落ちてもルールベースの工程がそのまま返る。
"""

from __future__ import annotations

from app.domain import makeup as makeup_rules
from app.domain.models import CharacterRef, FaceProfile, Lang, MakeupPlan
from app.ports.llm import LlmPort


class MakeupAgent:
    def __init__(self, llm: LlmPort) -> None:
        self.llm = llm

    async def enrich_character(
        self, character: CharacterRef, *, lang: Lang = Lang.JA
    ) -> CharacterRef:
        """髪色・瞳色が未入力なら LLM で補う。作品名・キャラ名は内部入力のまま。

        補完値は工程文へ埋め込まれるので、必ず出力言語で受け取る。
        """
        if character.hair_color and character.eye_color:
            return character
        hints = await self.llm.interpret_character(
            character.title, character.name, lang=lang.value
        )
        enriched = character.model_copy(deep=True)
        enriched.hair_color = enriched.hair_color or hints.get("hair_color")
        enriched.eye_color = enriched.eye_color or hints.get("eye_color")
        if not enriched.features:
            enriched.features = list(hints.get("features") or [])
        return enriched

    async def build(
        self,
        profile: FaceProfile,
        character: CharacterRef,
        *,
        lang: Lang = Lang.JA,
    ) -> MakeupPlan:
        """肌タイプ×顔属性×キャラの工程表を作り、母語で整える。"""
        enriched = await self.enrich_character(character, lang=lang)
        plan = makeup_rules.build_plan(profile, enriched, lang=lang)

        raw = [s.instruction for s in plan.steps]
        refined = await self.llm.refine_steps(raw, lang=lang.value, fallback=raw)
        # 件数が合わない応答はルールベースの結果を優先する
        if len(refined) == len(plan.steps):
            for step, text in zip(plan.steps, refined):
                step.instruction = text

        return plan

    def coverage(self, plan: MakeupPlan) -> dict[str, int]:
        """肌タイプ別の品質評価（設計書 §7-2）に使う個別化件数。"""
        return makeup_rules.personalization_coverage(plan)
