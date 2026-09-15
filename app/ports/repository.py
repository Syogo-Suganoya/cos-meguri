"""永続化のポート（Firestore / インメモリ）。

設計書 §6 のコレクション（layers / expeditions / favorites / chats / audit）に対応する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import AuditLog, ChatSession, Expedition, Favorite, Layer


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

    # -- expeditions ----------------------------------------------------
    @abstractmethod
    async def save_expedition(self, exp: Expedition) -> Expedition: ...

    @abstractmethod
    async def get_expedition(self, exp_id: str) -> Expedition | None: ...

    @abstractmethod
    async def list_expeditions(self, layer_id: str) -> list[Expedition]: ...

    # -- favorites -------------------------------------------------------
    @abstractmethod
    async def save_favorite(self, favorite: Favorite) -> Favorite: ...

    @abstractmethod
    async def get_favorite(self, favorite_id: str) -> Favorite | None: ...

    @abstractmethod
    async def list_favorites(self, layer_id: str) -> list[Favorite]:
        """本人のお気に入りを新しい順で返す。"""

    @abstractmethod
    async def delete_favorite(self, favorite_id: str) -> bool:
        """消せたら True。無ければ False。"""

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
