"""Firestore 実装（設計書 §6 のコレクション構成）。既定のデータ保存先。

google-cloud-firestore の同期クライアントをスレッドに逃がして使う。

**クエリは単一フィールドの等値だけに絞っている。** 複合条件は Firestore で
複合インデックスの作成を要求され、デプロイ手順に増える。件数が小さいうちは
1条件で引いて残りを Python 側で絞るほうが、運用の手数が少ない。
"""

from __future__ import annotations

import asyncio

from google.cloud import firestore

from app.domain.models import (
    AuditLog,
    ChatSession,
    Expedition,
    Favorite,
    Layer,
    utcnow,
)
from app.ports.repository import RepositoryPort

COL_LAYERS = "layers"
COL_EXPEDITIONS = "expeditions"
COL_FAVORITES = "favorites"
COL_CHATS = "chats"
COL_AUDIT = "audit"


class FirestoreRepository(RepositoryPort):
    name = "repository:firestore"

    def __init__(self, project: str) -> None:
        self._db = firestore.Client(project=project)

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def _set(self, collection: str, doc_id: str, data: dict) -> None:
        self._db.collection(collection).document(doc_id).set(data)

    def _get(self, collection: str, doc_id: str) -> dict | None:
        snap = self._db.collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    # -- layers ---------------------------------------------------------
    async def save_layer(self, layer: Layer) -> Layer:
        await self._run(self._set, COL_LAYERS, layer.layer_id, layer.model_dump(mode="json"))
        return layer

    async def get_layer(self, layer_id: str) -> Layer | None:
        data = await self._run(self._get, COL_LAYERS, layer_id)
        return Layer.model_validate(data) if data else None

    async def get_layer_by_uid(self, auth_uid: str) -> Layer | None:
        return await self._find_layer("auth_uid", auth_uid)

    async def _find_layer(self, field: str, value: str) -> Layer | None:
        def query() -> dict | None:
            docs = (
                self._db.collection(COL_LAYERS)
                .where(filter=firestore.FieldFilter(field, "==", value))
                .limit(1)
                .stream()
            )
            for doc in docs:
                return doc.to_dict()
            return None

        data = await self._run(query)
        return Layer.model_validate(data) if data else None

    # -- expeditions ----------------------------------------------------
    async def save_expedition(self, exp: Expedition) -> Expedition:
        exp.updated_at = utcnow()
        await self._run(self._set, COL_EXPEDITIONS, exp.exp_id, exp.model_dump(mode="json"))
        return exp

    async def get_expedition(self, exp_id: str) -> Expedition | None:
        data = await self._run(self._get, COL_EXPEDITIONS, exp_id)
        return Expedition.model_validate(data) if data else None

    async def list_expeditions(self, layer_id: str) -> list[Expedition]:
        def query() -> list[dict]:
            docs = (
                self._db.collection(COL_EXPEDITIONS)
                .where(filter=firestore.FieldFilter("layer_id", "==", layer_id))
                .stream()
            )
            return [d.to_dict() for d in docs]

        return [Expedition.model_validate(d) for d in await self._run(query)]

    # -- favorites -------------------------------------------------------
    async def save_favorite(self, favorite: Favorite) -> Favorite:
        await self._run(
            self._set, COL_FAVORITES, favorite.favorite_id, favorite.model_dump(mode="json")
        )
        return favorite

    async def get_favorite(self, favorite_id: str) -> Favorite | None:
        data = await self._run(self._get, COL_FAVORITES, favorite_id)
        return Favorite.model_validate(data) if data else None

    async def list_favorites(self, layer_id: str) -> list[Favorite]:
        def query() -> list[dict]:
            docs = (
                self._db.collection(COL_FAVORITES)
                .where(filter=firestore.FieldFilter("layer_id", "==", layer_id))
                .stream()
            )
            return [d.to_dict() for d in docs]

        # 並べ替えは Python 側。order_by を足すと複合インデックスが要る
        items = [Favorite.model_validate(d) for d in await self._run(query)]
        return sorted(items, key=lambda f: f.created_at, reverse=True)

    async def delete_favorite(self, favorite_id: str) -> bool:
        def delete() -> bool:
            ref = self._db.collection(COL_FAVORITES).document(favorite_id)
            if not ref.get().exists:
                return False
            ref.delete()
            return True

        return await self._run(delete)

    # -- chat ------------------------------------------------------------
    async def save_chat(self, session: ChatSession) -> ChatSession:
        session.updated_at = utcnow()
        await self._run(self._set, COL_CHATS, session.layer_id, session.model_dump(mode="json"))
        return session

    async def get_chat(self, layer_id: str) -> ChatSession | None:
        data = await self._run(self._get, COL_CHATS, layer_id)
        return ChatSession.model_validate(data) if data else None

    # -- audit ----------------------------------------------------------
    async def append_audit(self, log: AuditLog) -> AuditLog:
        await self._run(self._set, COL_AUDIT, log.log_id, log.model_dump(mode="json"))
        return log

    async def list_audit(
        self, *, subject_id: str | None = None, layer_id: str | None = None
    ) -> list[AuditLog]:
        def query() -> list[dict]:
            col = self._db.collection(COL_AUDIT)
            # 複合インデックスを要らなくするため、絞り込みは等値1つまで。
            # 残りは Python 側で落とす（他のクエリと同じ方針）
            if subject_id:
                col = col.where(filter=firestore.FieldFilter("subject_id", "==", subject_id))
            elif layer_id:
                col = col.where(
                    filter=firestore.FieldFilter("layer_ids", "array_contains", layer_id)
                )
            return [d.to_dict() for d in col.stream()]

        logs = [AuditLog.model_validate(d) for d in await self._run(query)]
        if subject_id and layer_id:
            logs = [log for log in logs if layer_id in log.layer_ids]
        return logs

