"""メイク工程の組み立てを検証する（設計書 §4 メイクナビ）。

肌タイプ・顔比率による個別化は取り下げた（判定に使っていた YouCam を外し、
測っていない数値で分岐させないため）。いまの工程はキャラの色味と造形から組む。
"""

from __future__ import annotations

from app.domain.makeup import build_plan
from app.domain.models import CharacterRef, Lang, MakeupArea

CHARACTER = CharacterRef(title="作品A", name="キャラB", hair_color="銀", eye_color="赤")


def has_japanese(text: str) -> bool:
    """仮名だけでなく漢字も見る。色名の混入は漢字1文字で起きる。"""
    return any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)


def test_all_nine_areas_are_present_in_order():
    """工程は9つ。塗り重ねの順序どおりで、重複しない。"""
    plan = build_plan(CHARACTER)
    areas = [s.area for s in plan.steps]
    assert len(areas) == 9
    assert areas == list(dict.fromkeys(areas))
    assert [s.order for s in plan.steps] == list(range(1, 10))


def test_no_skin_lightening_instructions():
    """肌の明度そのものを変える指示を出さない（設計書 §7-2）。

    肌タイプで分岐しなくなっても、この線は引き続き守る。
    """
    text = " ".join(s.instruction for s in build_plan(CHARACTER).steps)
    for banned in ["美白", "白くする", "肌を明るく", "ワントーン上げ", "肌を暗く"]:
        assert banned not in text


def test_nothing_claims_to_have_measured_the_face():
    """顔を見ていないので、見たふりの文言を出さない。

    肌タイプや顔比率に言及すると、測っていない値で語ったことになる。
    """
    plan = build_plan(CHARACTER)
    text = " ".join(s.instruction for s in plan.steps)
    text += " ".join(r for s in plan.steps for r in s.personalized_for)
    for banned in ["肌タイプ", "彫りが", "彫りは", "離れ目", "寄り目", "面長", "エラが"]:
        assert banned not in text, banned

    # 見ていないことは注記で明示する
    assert any("見ていない" in note for note in plan.notes)


def test_character_colours_reach_the_steps():
    """キャラの髪色・瞳色が工程文に入る（ここが個別化の軸になった）。"""
    plan = build_plan(CHARACTER)

    def step(area) -> str:
        return next(s.instruction for s in plan.steps if s.area is area)

    assert "銀" in step(MakeupArea.BROW)
    assert "赤" in step(MakeupArea.EYESHADOW)
    assert "赤" in step(MakeupArea.LENS)


def test_every_step_carries_a_reason():
    """どの工程にも根拠が付く（可観測性）。空の工程を作らない。"""
    for step in build_plan(CHARACTER).steps:
        assert step.personalized_for, f"{step.area} に根拠がない"


def test_english_plan_is_fully_translated():
    """英語指定で日本語が混ざらない（インバウンド対応の最低条件）。"""
    english = CharacterRef(
        title="Series A", name="Character B", hair_color="silver", eye_color="red"
    )
    plan = build_plan(english, lang=Lang.EN)
    joined = " ".join(s.instruction for s in plan.steps)
    assert not has_japanese(joined), joined
    assert plan.lang is Lang.EN
    assert all(not has_japanese(note) for note in plan.notes)


def test_missing_character_colours_do_not_leave_holes():
    """髪色・瞳色が埋まっていなくても、工程文が欠けない。"""
    bare = CharacterRef(title="作品", name="キャラ")
    plan = build_plan(bare)
    assert len(plan.steps) == 9
    for step in plan.steps:
        assert step.instruction.strip()
        assert "None" not in step.instruction


def test_total_minutes_matches_steps():
    plan = build_plan(CHARACTER)
    assert plan.total_minutes == sum(s.minutes for s in plan.steps)
    assert plan.total_minutes > 0
