"""Firestore アダプタの結合テスト。エミュレータに実際に読み書きする。

```
docker compose --profile itest run --rm test-firestore
```

インメモリ実装と同じ契約で動くことを確かめるのが目的。ここが通らないと、
ローカルでは動くのに本番で壊れる、という一番たちの悪い失敗をする。
FIRESTORE_EMULATOR_HOST が無い環境では丸ごとスキップする。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.models import (
    AuditAction,
    AuditLog,
    CharacterRef,
    ChatSession,
    EventRef,
    Expedition,
    ExpeditionStatus,
    Favorite,
    FavoriteKind,
    Lang,
    Layer,
    LuggageMode,
    MakeupPlan,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    reason="Firestore エミュレータが無い（--profile itest で実行する）",
)

DAY = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo():
    from app.adapters.firestore_repo import FirestoreRepository

    return FirestoreRepository(os.environ.get("GOOGLE_CLOUD_PROJECT", "cos-meguri-local"))


def _uid() -> str:
    """テスト間でドキュメントが衝突しないようにする（エミュレータは共有）。"""
    return uuid.uuid4().hex[:8]


def _event(event_id: str = "acosta") -> EventRef:
    return EventRef(
        event_id=event_id,
        name="acosta!",
        venue="池袋・ハレザ",
        starts_at=DAY,
        ends_at=DAY.replace(hour=17),
    )


# ---------------------------------------------------------------- レイヤー


async def test_layer_roundtrip_keeps_every_field(repo):
    """入れ子（設定）と列挙型が往復しても壊れない。"""
    layer = Layer(
        layer_id=f"ly_{_uid()}",
        lang=Lang.EN,
        auth_uid=f"uid_{_uid()}",
    )
    layer.prefs.luggage_mode = LuggageMode.HEAVY
    await repo.save_layer(layer)

    stored = await repo.get_layer(layer.layer_id)
    assert stored is not None
    assert stored.auth_uid == layer.auth_uid
    assert stored.lang is Lang.EN
    assert stored.prefs.luggage_mode is LuggageMode.HEAVY


async def test_layer_can_be_found_by_uid(repo):
    uid = f"uid_{_uid()}"
    layer = Layer(layer_id=f"ly_{_uid()}", auth_uid=uid)
    await repo.save_layer(layer)

    assert (await repo.get_layer_by_uid(uid)).layer_id == layer.layer_id
    assert await repo.get_layer_by_uid(f"uid_{_uid()}") is None


async def test_layer_saved_with_a_handle_still_loads(repo):
    """レイヤー名を持っていた頃のドキュメントも読める。落ちるとその人はログインできない。"""
    layer_id, uid = f"ly_{_uid()}", f"uid_{_uid()}"
    await repo._run(
        repo._set,
        "layers",
        layer_id,
        {"layer_id": layer_id, "handle": "レイヤーD977D4", "auth_uid": uid, "lang": "ja"},
    )
    stored = await repo.get_layer_by_uid(uid)
    assert stored.layer_id == layer_id
    assert "handle" not in stored.model_dump()


async def test_missing_document_returns_none(repo):
    assert await repo.get_layer(f"ly_{_uid()}") is None
    assert await repo.get_chat(f"ly_{_uid()}") is None


# ---------------------------------------------------------------- 遠征


async def test_expedition_is_listed_by_owner_and_by_date(repo):
    layer_id = f"ly_{_uid()}"
    exp = Expedition(
        exp_id=f"exp_{_uid()}",
        layer_id=layer_id,
        status=ExpeditionStatus.PLANNED,
        event=_event(),
        event_date=_event().date_key,
        character=CharacterRef(title="作品A", name="キャラB"),
    )
    await repo.save_expedition(exp)

    mine = await repo.list_expeditions(layer_id)
    assert [e.exp_id for e in mine] == [exp.exp_id]


async def test_saving_twice_updates_instead_of_duplicating(repo):
    exp = Expedition(
        exp_id=f"exp_{_uid()}",
        layer_id=f"ly_{_uid()}",
        event=_event(),
        event_date=_event().date_key,
        character=CharacterRef(title="作品A", name="キャラB"),
    )
    await repo.save_expedition(exp)
    exp.status = ExpeditionStatus.PLANNED
    await repo.save_expedition(exp)

    stored = await repo.list_expeditions(exp.layer_id)
    assert len(stored) == 1
    assert stored[0].status is ExpeditionStatus.PLANNED


async def test_expedition_saved_with_a_dressing_forecast_still_loads(repo):
    """更衣室の予測を持っていた頃の遠征も読める。落ちるとプランのページが開かない。"""
    exp = Expedition(
        exp_id=f"exp_{_uid()}",
        layer_id=f"ly_{_uid()}",
        event=_event(),
        event_date=_event().date_key,
        character=CharacterRef(title="作品A", name="キャラB"),
    )
    data = exp.model_dump(mode="json")
    data["dressing"] = {"event_id": "acosta", "slots": [], "is_model_estimate": True}
    await repo._run(repo._set, "expeditions", exp.exp_id, data)

    stored = await repo.get_expedition(exp.exp_id)
    assert stored.exp_id == exp.exp_id
    assert "dressing" not in stored.model_dump()


# ---------------------------------------------------------------- お気に入り


async def test_favorites_are_listed_newest_first_and_can_be_deleted(repo):
    layer_id, other = f"ly_{_uid()}", f"ly_{_uid()}"
    old = Favorite(
        favorite_id=f"fav_{_uid()}",
        layer_id=layer_id,
        kind=FavoriteKind.MAKEUP,
        label="古い",
        exp_id=f"exp_{_uid()}",
        event=_event(),
        makeup=MakeupPlan(total_minutes=10),
        created_at=DAY,
    )
    new = old.model_copy(
        update={"favorite_id": f"fav_{_uid()}", "label": "新しい", "created_at": DAY.replace(hour=12)}
    )
    theirs = old.model_copy(update={"favorite_id": f"fav_{_uid()}", "layer_id": other})
    for f in (old, new, theirs):
        await repo.save_favorite(f)

    mine = await repo.list_favorites(layer_id)
    assert [f.label for f in mine] == ["新しい", "古い"]
    assert mine[0].makeup.total_minutes == 10

    assert await repo.delete_favorite(old.favorite_id) is True
    assert await repo.delete_favorite(old.favorite_id) is False
    assert [f.label for f in await repo.list_favorites(layer_id)] == ["新しい"]


# ---------------------------------------------------------------- チャット


async def test_chat_session_roundtrip(repo):
    layer_id = f"ly_{_uid()}"
    session = ChatSession(layer_id=layer_id, lang=Lang.JA)
    session.slots.event_id = "comiket"
    session.slots.day = DAY
    session.slots.luggage_mode = LuggageMode.HEAVY
    await repo.save_chat(session)

    stored = await repo.get_chat(layer_id)
    assert stored.slots.event_id == "comiket"
    assert stored.slots.luggage_mode is LuggageMode.HEAVY
    assert stored.slots.day.date() == DAY.date()


async def test_chat_saved_by_the_old_free_text_version_still_loads(repo):
    """自由文の会話を持っていた頃のドキュメントには messages が残っている。

    読めずに落ちると、その人は「相談」ページを開いた瞬間から先へ進めなくなる。
    """
    layer_id = f"ly_{_uid()}"
    await repo._run(
        repo._set,
        "chats",
        layer_id,
        {
            "layer_id": layer_id,
            "lang": "ja",
            "messages": [{"role": "user", "text": "コミケに行きます"}],
            "slots": {"event_id": "comiket"},
        },
    )
    stored = await repo.get_chat(layer_id)
    assert stored.slots.event_id == "comiket"


async def test_chat_saved_with_only_an_event_id_keeps_its_destination_and_times(repo):
    """目的地と開始・終了を持つ前のドキュメント。補わないと、組み上がっていた条件が「足りない」に戻る。"""
    layer_id = f"ly_{_uid()}"
    await repo._run(
        repo._set,
        "chats",
        layer_id,
        {
            "layer_id": layer_id,
            "lang": "ja",
            "slots": {
                "event_id": "acosta",
                "day": DAY.isoformat(),
                "title": "作品A",
                "character": "キャラB",
                "origin_station": "横浜",
                "luggage_mode": "carry",
            },
            "exp_id": "exp_old",
        },
    )
    stored = await repo.get_chat(layer_id)
    assert stored.slots.is_complete
    assert (stored.slots.event_name, stored.slots.destination_station) == ("acosta!", "池袋")
    assert (stored.slots.starts_time, stored.slots.ends_time) == ("10:00", "17:00")


# ---------------------------------------------------------------- 監査


async def test_audit_can_be_filtered_by_subject(repo):
    subject = f"ly_{_uid()}"
    await repo.append_audit(
        AuditLog(
            log_id=f"log_{_uid()}",
            actor=subject,
            action=AuditAction.FACE_IMAGE_DISCARDED,
            subject_id=subject,
            payload={"image_retained": False},
        )
    )
    logs = await repo.list_audit(subject_id=subject)
    assert len(logs) == 1
    assert logs[0].action is AuditAction.FACE_IMAGE_DISCARDED
    assert logs[0].payload["image_retained"] is False
