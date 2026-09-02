"""インメモリの永続化。ローカル開発と単体テストの既定。

Firestore アダプタと同じ契約で動くよう、保存時は必ずディープコピーを取る
（呼び出し側がモデルを書き換えても保存済みデータが変わらないこと）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain import awase as awase_domain
from app.domain.models import (
    AuditAction,
    AuditLog,
    Awase,
    ChatSession,
    Expedition,
    ExpeditionStatus,
    Layer,
    Notification,
    utcnow,
)
from app.ports.repository import RepositoryPort


class MemoryRepository(RepositoryPort):
    name = "repository:memory"

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}
        self._expeditions: dict[str, Expedition] = {}
        self._awase: dict[str, Awase] = {}
        self._notifications: list[Notification] = []
        self._chats: dict[str, ChatSession] = {}
        self._audit: list[AuditLog] = []

    # -- layers ---------------------------------------------------------
    async def save_layer(self, layer: Layer) -> Layer:
        self._layers[layer.layer_id] = layer.model_copy(deep=True)
        return layer

    async def get_layer(self, layer_id: str) -> Layer | None:
        found = self._layers.get(layer_id)
        return found.model_copy(deep=True) if found else None

    async def get_layer_by_uid(self, auth_uid: str) -> Layer | None:
        for layer in self._layers.values():
            if layer.auth_uid == auth_uid:
                return layer.model_copy(deep=True)
        return None

    async def find_layer_by_handle(self, handle: str) -> Layer | None:
        for layer in self._layers.values():
            if layer.handle == handle:
                return layer.model_copy(deep=True)
        return None

    # -- expeditions ----------------------------------------------------
    async def save_expedition(self, exp: Expedition) -> Expedition:
        exp.updated_at = utcnow()
        self._expeditions[exp.exp_id] = exp.model_copy(deep=True)
        return exp

    async def get_expedition(self, exp_id: str) -> Expedition | None:
        found = self._expeditions.get(exp_id)
        return found.model_copy(deep=True) if found else None

    async def list_expeditions(self, layer_id: str) -> list[Expedition]:
        return [
            e.model_copy(deep=True)
            for e in self._expeditions.values()
            if e.layer_id == layer_id
        ]

    async def list_expeditions_on(self, event_date: str) -> list[Expedition]:
        return [
            e.model_copy(deep=True)
            for e in self._expeditions.values()
            if e.event_date == event_date and e.status is not ExpeditionStatus.DONE
        ]

    # -- awase ----------------------------------------------------------
    async def save_awase(self, awase: Awase) -> Awase:
        self._awase[awase.awase_id] = awase.model_copy(deep=True)
        return awase

    async def get_awase(self, awase_id: str) -> Awase | None:
        found = self._awase.get(awase_id)
        return found.model_copy(deep=True) if found else None

    async def list_awase(self) -> list[Awase]:
        return [a.model_copy(deep=True) for a in self._awase.values()]

    # -- notifications ---------------------------------------------------
    async def save_notification(self, notification: Notification) -> Notification:
        self._notifications.append(notification.model_copy(deep=True))
        return notification

    async def list_notifications(
        self, layer_id: str, *, unread_only: bool = False
    ) -> list[Notification]:
        found = [n for n in self._notifications if n.layer_id == layer_id]
        if unread_only:
            found = [n for n in found if not n.read]
        return [
            n.model_copy(deep=True)
            for n in sorted(found, key=lambda n: n.created_at, reverse=True)
        ]

    async def mark_notifications_read(self, layer_id: str, ids: list[str]) -> int:
        wanted = set(ids)
        count = 0
        for n in self._notifications:
            if n.layer_id == layer_id and n.notification_id in wanted and not n.read:
                n.read = True
                count += 1
        return count

    # -- chat ------------------------------------------------------------
    async def save_chat(self, session: ChatSession) -> ChatSession:
        session.updated_at = utcnow()
        self._chats[session.layer_id] = session.model_copy(deep=True)
        return session

    async def get_chat(self, layer_id: str) -> ChatSession | None:
        found = self._chats.get(layer_id)
        return found.model_copy(deep=True) if found else None

    # -- audit ----------------------------------------------------------
    async def append_audit(self, log: AuditLog) -> AuditLog:
        self._audit.append(log.model_copy(deep=True))
        return log

    async def list_audit(self, *, subject_id: str | None = None) -> list[AuditLog]:
        logs = [log.model_copy(deep=True) for log in self._audit]
        if subject_id:
            logs = [log for log in logs if log.subject_id == subject_id]
        return logs

    # -- TTL ------------------------------------------------------------
    async def purge_expired(self, *, now: datetime | None = None) -> list[str]:
        """設計書 §7-3: 期限切れの位置共有と、TTL到達の合わせを落とす。"""
        now = now or utcnow()
        purged: list[str] = []

        for awase_id, stored in list(self._awase.items()):
            cleaned, purged_members = awase_domain.purge_expired_locations(stored, now=now)
            if purged_members:
                self._awase[awase_id] = cleaned
                purged.append(awase_id)
                await self.append_audit(
                    AuditLog(
                        log_id=f"log_{uuid.uuid4().hex[:8]}",
                        actor="scheduler",
                        action=AuditAction.LOCATION_SHARE_PURGED,
                        subject_id=awase_id,
                        payload={"members": purged_members},
                    )
                )

            if awase_domain.should_purge(cleaned, now=now):
                # 進捗・位置は履歴ごと落とす。枠と表題だけを残す
                stripped = cleaned.model_copy(deep=True)
                stripped.members = []
                stripped.proposals = []
                self._awase[awase_id] = stripped
                await self.append_audit(
                    AuditLog(
                        log_id=f"log_{uuid.uuid4().hex[:8]}",
                        actor="scheduler",
                        action=AuditAction.EXPEDITION_PURGED,
                        subject_id=awase_id,
                        payload={"reason": "ttl", "ttl_at": cleaned.ttl_at.isoformat()},
                    )
                )
                if awase_id not in purged:
                    purged.append(awase_id)

        return purged
