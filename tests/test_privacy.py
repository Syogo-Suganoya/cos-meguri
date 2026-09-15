"""プライバシー設計（設計書 §7-4）の検証。"""

from __future__ import annotations

from app.domain import guardrails
from app.domain.models import CharacterRef


def test_character_names_are_stripped_from_shared_text():
    char = CharacterRef(title="作品X", name="キャラY")
    text = "今日は作品XのキャラYで参加します"
    assert guardrails.shareable_summary(text, char) == "今日は＊＊の＊＊で参加します"


def test_records_are_scoped_to_the_person_they_belong_to(user, login):
    """記録は本人ぶんだけ返す。以前は絞り込み無しで全員ぶんが見えていた。"""
    mine = user.get("/api/audit").json()["logs"]
    assert mine, "自分の記録が1件も無い"
    assert all(user.layer_id in log["layer_ids"] for log in mine)

    # 他人の記録は1件も混ざらない（自分のログイン記録だけが見える）
    stranger = login("無関係な人")
    theirs = stranger.get("/api/audit").json()["logs"]
    assert all(stranger.layer_id in log["layer_ids"] for log in theirs)
    assert not any(user.layer_id in log["layer_ids"] for log in theirs)
