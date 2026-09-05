"""永続化のポート（Firestore / インメモリ）。

設計書 §6 のコレクション（layers / expeditions / awase / audit）に対応する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import (
    AuditLog,
    Awase,
    ChatSession,
    Expedition,
    Layer,
    Notification,
)


class RepositoryPort(ABC):
    name: str = "repository"

    # -- layers ---------------------------------------------------------
    @abstractmethod
    async def save_layer(self, layer: Layer) -> Layer: ...

    @abstractmethod
    async def get_layer(self, layer_id: str) -> Layer | None: ...

    @abstractmethod
    async def get_layer_by_uid(self, auth_uid: str) -> Layer | None:
        """認証IDからコス名アカウントを引く。ログインのたびに使う。"""

    @abstractmethod
    async def find_layer_by_handle(self, handle: str) -> Layer | None:
        """コス名で引く。合わせの招待（未ログインの相手）で使う。"""

    # -- expeditions ----------------------------------------------------
    @abstractmethod
    async def save_expedition(self, exp: Expedition) -> Expedition: ...

    @abstractmethod
    async def get_expedition(self, exp_id: str) -> Expedition | None: ...

    @abstractmethod
    async def list_expeditions(self, layer_id: str) -> list[Expedition]: ...

    # -- awase ----------------------------------------------------------
    @abstractmethod
    async def save_awase(self, awase: Awase) -> Awase: ...

    @abstractmethod
    async def get_awase(self, awase_id: str) -> Awase | None: ...

    @abstractmethod
    async def list_awase(self) -> list[Awase]: ...

    # -- notifications ---------------------------------------------------
    @abstractmethod
    async def save_notification(self, notification: Notification) -> Notification: ...

    @abstractmethod
    async def list_notifications(
        self, layer_id: str, *, unread_only: bool = False
    ) -> list[Notification]: ...

    @abstractmethod
    async def mark_notifications_read(self, layer_id: str, ids: list[str]) -> int: ...

    # -- chat ------------------------------------------------------------
    @abstractmethod
    async def save_chat(self, session: ChatSession) -> ChatSession: ...

    @abstractmethod
    async def get_chat(self, layer_id: str) -> ChatSession | None: ...

    # -- audit ----------------------------------------------------------
    @abstractmethod
    async def append_audit(self, log: AuditLog) -> AuditLog: ...

    @abstractmethod
    async def list_audit(
        self, *, subject_id: str | None = None, layer_id: str | None = None
    ) -> list[AuditLog]: ...

