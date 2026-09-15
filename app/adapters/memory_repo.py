"""インメモリの永続化。ローカル開発と単体テストの既定。

Firestore アダプタと同じ契約で動くよう、保存時は必ずディープコピーを取る
（呼び出し側がモデルを書き換えても保存済みデータが変わらないこと）。
"""

from __future__ import annotations

from app.domain.models import AuditLog, ChatSession, Expedition, Favorite, Layer, utcnow
from app.ports.repository import RepositoryPort


class MemoryRepository(RepositoryPort):
    name = "repository:memory"

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}
        self._expeditions: dict[str, Expedition] = {}
        self._favorites: dict[str, Favorite] = {}
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

    # -- favorites -------------------------------------------------------
    async def save_favorite(self, favorite: Favorite) -> Favorite:
        self._favorites[favorite.favorite_id] = favorite.model_copy(deep=True)
        return favorite

    async def get_favorite(self, favorite_id: str) -> Favorite | None:
        found = self._favorites.get(favorite_id)
        return found.model_copy(deep=True) if found else None

    async def list_favorites(self, layer_id: str) -> list[Favorite]:
        mine = [f for f in self._favorites.values() if f.layer_id == layer_id]
        return [
            f.model_copy(deep=True)
            for f in sorted(mine, key=lambda f: f.created_at, reverse=True)
        ]

    async def delete_favorite(self, favorite_id: str) -> bool:
        return self._favorites.pop(favorite_id, None) is not None

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

    async def list_audit(
        self, *, subject_id: str | None = None, layer_id: str | None = None
    ) -> list[AuditLog]:
        logs = [log.model_copy(deep=True) for log in self._audit]
        if subject_id:
            logs = [log for log in logs if log.subject_id == subject_id]
        if layer_id:
            logs = [log for log in logs if layer_id in log.layer_ids]
        return logs
