"""メイク工程の個別化と公平性（設計書 §7-2）を検証する。"""

from __future__ import annotations

import pytest

from app.domain.makeup import build_plan
from app.domain.models import (
    CharacterRef,
    FaceAttributes,
    FaceProfile,
    FitzpatrickType,
    Lang,
    MakeupArea,
)

CHARACTER = CharacterRef(title="作品A", name="キャラB", hair_color="銀", eye_color="赤")


def profile(skin: FitzpatrickType, **attrs) -> FaceProfile:
    return FaceProfile(fitzpatrick_type=skin, attributes=FaceAttributes(**attrs))


def has_japanese(text: str) -> bool:
    """仮名だけでなく漢字も見る。色名の混入は漢字1文字で起きる。"""
    return any(
        "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text
    )


def test_all_areas_present_for_every_skin_type():
    """どの肌タイプでも工程数が落ちない（品質の下限を揃える）。"""
    counts = set()
    for skin in FitzpatrickType:
        plan = build_plan(profile(skin), CHARACTER)
        assert [s.area for s in plan.steps] == list(
            dict.fromkeys(s.area for s in plan.steps)
        )
        assert len(plan.steps) == 9
        counts.add(len(plan.steps))
    assert counts == {9}


@pytest.mark.parametrize("skin", list(FitzpatrickType))
def test_no_skin_lightening_instructions(skin: FitzpatrickType):
    """肌の明度そのものを変える指示を出さない（設計書 §7-2）。"""
    plan = build_plan(profile(skin), CHARACTER)
    text = " ".join(s.instruction for s in plan.steps)
    for banned in ["美白", "白くする", "肌を明るく", "ワントーン上げ", "肌を暗く"]:
        assert banned not in text


def test_deep_and_light_skin_get_different_base_and_highlight():
    """肌タイプで下地とハイライトの指示が実際に変わる。"""
    deep = build_plan(profile(FitzpatrickType.VI), CHARACTER)
    light = build_plan(profile(FitzpatrickType.I), CHARACTER)

    def step(plan, area):
        return next(s for s in plan.steps if s.area is area)

    assert step(deep, MakeupArea.BASE).instruction != step(light, MakeupArea.BASE).instruction
    assert (
        step(deep, MakeupArea.HIGHLIGHT).instruction
        != step(light, MakeupArea.HIGHLIGHT).instruction
    )
    assert "白浮き" in step(deep, MakeupArea.BASE).instruction


@pytest.mark.parametrize("skin", list(FitzpatrickType))
def test_every_step_carries_personalization_reason(skin: FitzpatrickType):
    """どの工程にも個別化の根拠が付く（可観測性: 設計書 §7-2）。

    属性が中庸（全て0.5）のときも根拠が空にならないこと。中庸を「説明不要な
    標準」として扱うと、そこだけ理由の見えない工程になってしまう。
    """
    plan = build_plan(profile(skin), CHARACTER)
    for step in plan.steps:
        assert step.personalized_for, f"{skin} / {step.area} に個別化根拠がない"


def test_eye_distance_changes_eyeliner_direction():
    """離れ目と寄り目でアイラインの足す側が入れ替わる。"""
    wide = build_plan(profile(FitzpatrickType.III, eye_distance=0.9), CHARACTER)
    narrow = build_plan(profile(FitzpatrickType.III, eye_distance=0.1), CHARACTER)

    def eyeline(plan) -> str:
        return next(s for s in plan.steps if s.area is MakeupArea.EYELINE).instruction

    assert "目頭側にラインを足して" in eyeline(wide)
    assert "目尻側を長めに" in eyeline(narrow)


def test_deep_iris_gets_opaque_lens_guidance():
    """虹彩が濃い場合はベース入りカラコンを案内する。"""
    plan = build_plan(profile(FitzpatrickType.V), CHARACTER)
    lens = next(s for s in plan.steps if s.area is MakeupArea.LENS).instruction
    assert "ベース入り" in lens


def test_english_plan_is_fully_translated():
    """英語指定で日本語が混ざらない（インバウンド対応の最低条件）。"""
    english_character = CharacterRef(
        title="Series A", name="Character B", hair_color="silver", eye_color="red"
    )
    plan = build_plan(profile(FitzpatrickType.V), english_character, lang=Lang.EN)
    joined = " ".join(s.instruction for s in plan.steps)
    assert not has_japanese(joined), joined
    assert plan.lang is Lang.EN


def test_total_minutes_matches_steps():
    plan = build_plan(profile(FitzpatrickType.II), CHARACTER)
    assert plan.total_minutes == sum(s.minutes for s in plan.steps)
    assert plan.total_minutes > 0
