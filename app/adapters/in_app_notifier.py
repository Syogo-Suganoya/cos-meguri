"""アプリ内お知らせの実装。保存先は RepositoryPort に委ねる。

外部サービスに送らないので mock / live の区別が無い。メモリでも Firestore でも
同じこの実装が動く（差し替わるのは下のリポジトリだけ）。
"""

from __future__ import annotations

import uuid

from app.domain.models import Lang, Notification, NotificationKind
from app.ports.notifier import NotifierPort
from app.ports.repository import RepositoryPort


class InAppNotifier(NotifierPort):
    name = "notifier:in_app"

    def __init__(self, repository: RepositoryPort) -> None:
        self.repository = repository

    async def push(
        self,
        *,
        layer_id: str,
        message: str,
        kind: NotificationKind = NotificationKind.INFO,
        lang: Lang = Lang.JA,
        awase_id: str | None = None,
        exp_id: str | None = None,
    ) -> Notification:
        return await self.repository.save_notification(
            Notification(
                notification_id=f"ntf_{uuid.uuid4().hex[:8]}",
                layer_id=layer_id,
                kind=kind,
                message=message,
                lang=lang,
                awase_id=awase_id,
                exp_id=exp_id,
            )
        )

    async def broadcast(
        self,
        *,
        layer_ids: list[str],
        message: str,
        kind: NotificationKind = NotificationKind.INFO,
        awase_id: str | None = None,
    ) -> list[Notification]:
        return [
            await self.push(
                layer_id=layer_id, message=message, kind=kind, awase_id=awase_id
            )
            for layer_id in layer_ids
        ]

    async def inbox(self, layer_id: str, *, unread_only: bool = False) -> list[Notification]:
        return await self.repository.list_notifications(layer_id, unread_only=unread_only)

    async def mark_read(self, layer_id: str, notification_ids: list[str]) -> int:
        return await self.repository.mark_notifications_read(layer_id, notification_ids)
