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
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import awase as awase_rules
from app.domain.models import (
    AuditAction,
    AuditLog,
    Awase,
    AwaseMember,
    CharacterRef,
    ChatMessage,
    ChatRole,
    ChatSession,
    EventRef,
    Expedition,
    ExpeditionStatus,
    FaceAttributes,
    FaceProfile,
    FitzpatrickType,
    Lang,
    Layer,
    LuggageMode,
    Notification,
    NotificationKind,
    Shoot,
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
    """入れ子（顔属性）と列挙型が往復しても壊れない。"""
    layer = Layer(
        layer_id=f"ly_{_uid()}",
        handle=f"テスト{_uid()}",
        lang=Lang.EN,
        auth_uid=f"uid_{_uid()}",
        face_profile=FaceProfile(
            fitzpatrick_type=FitzpatrickType.V,
            attributes=FaceAttributes(brow_depth=0.81, eye_distance=0.22),
        ),
    )
    layer.prefs.luggage_mode = LuggageMode.HEAVY
    await repo.save_layer(layer)

    stored = await repo.get_layer(layer.layer_id)
    assert stored is not None
    assert stored.handle == layer.handle
    assert stored.lang is Lang.EN
    assert stored.prefs.luggage_mode is LuggageMode.HEAVY
    assert stored.face_profile.fitzpatrick_type is FitzpatrickType.V
    assert stored.face_profile.attributes.brow_depth == 0.81
    assert stored.face_profile.source_image_discarded is True


async def test_layer_can_be_found_by_uid_and_handle(repo):
    uid, handle = f"uid_{_uid()}", f"コス名{_uid()}"
    layer = Layer(layer_id=f"ly_{_uid()}", handle=handle, auth_uid=uid)
    await repo.save_layer(layer)

    assert (await repo.get_layer_by_uid(uid)).layer_id == layer.layer_id
    assert (await repo.find_layer_by_handle(handle)).layer_id == layer.layer_id
    assert await repo.get_layer_by_uid(f"uid_{_uid()}") is None


async def test_missing_document_returns_none(repo):
    assert await repo.get_layer(f"ly_{_uid()}") is None
    assert await repo.get_awase(f"aw_{_uid()}") is None
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
    exp.status = ExpeditionStatus.DAY_OF
    await repo.save_expedition(exp)

    stored = await repo.list_expeditions(exp.layer_id)
    assert len(stored) == 1
    assert stored[0].status is ExpeditionStatus.DAY_OF


# ---------------------------------------------------------------- お知らせ


async def test_notifications_are_scoped_and_ordered(repo):
    mine, other = f"ly_{_uid()}", f"ly_{_uid()}"
    old = Notification(
        notification_id=f"ntf_{_uid()}",
        layer_id=mine,
        kind=NotificationKind.TEARDOWN,
        message="古い",
        created_at=DAY,
    )
    new = Notification(
        notification_id=f"ntf_{_uid()}",
        layer_id=mine,
        kind=NotificationKind.ROUTE_DELAY,
        message="新しい",
        created_at=DAY + timedelta(hours=1),
    )
    theirs = Notification(
        notification_id=f"ntf_{_uid()}", layer_id=other, message="他人あて"
    )
    for n in (old, new, theirs):
        await repo.save_notification(n)

    items = await repo.list_notifications(mine)
    assert [n.message for n in items] == ["新しい", "古い"]  # 新しい順
    assert all(n.layer_id == mine for n in items)


async def test_marking_read_ignores_other_peoples_notifications(repo):
    mine, other = f"ly_{_uid()}", f"ly_{_uid()}"
    a = Notification(notification_id=f"ntf_{_uid()}", layer_id=mine, message="自分あて")
    b = Notification(notification_id=f"ntf_{_uid()}", layer_id=other, message="他人あて")
    await repo.save_notification(a)
    await repo.save_notification(b)

    # 他人あてのIDを混ぜても既読にできない
    assert await repo.mark_notifications_read(mine, [a.notification_id, b.notification_id]) == 1
    assert await repo.list_notifications(mine, unread_only=True) == []
    assert len(await repo.list_notifications(other, unread_only=True)) == 1

    # 二度目は既読済みなので0件
    assert await repo.mark_notifications_read(mine, [a.notification_id]) == 0


# ---------------------------------------------------------------- チャット


async def test_chat_session_roundtrip(repo):
    layer_id = f"ly_{_uid()}"
    session = ChatSession(layer_id=layer_id, lang=Lang.JA)
    session.messages.append(ChatMessage(role=ChatRole.USER, text="コミケに行きます"))
    session.slots.event_id = "comiket"
    session.slots.day = DAY
    session.slots.luggage_mode = LuggageMode.HEAVY
    await repo.save_chat(session)

    stored = await repo.get_chat(layer_id)
    assert stored.messages[0].role is ChatRole.USER
    assert stored.slots.event_id == "comiket"
    assert stored.slots.luggage_mode is LuggageMode.HEAVY
    assert stored.slots.day.date() == DAY.date()


# ---------------------------------------------------------------- 合わせ


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
