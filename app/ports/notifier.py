"""アプリ内お知らせのポート。

外部メッセージング（LINE等）は使わない。当日モードの自律通知
（動線の再計算・撤収アラート・リスケの承認依頼）も、すべてアプリ内の
お知らせ欄へ積む。宛先はコス名アカウント（layerId）だけで、
電話番号・端末トークンといった連絡先は一切持たない。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import Lang, Notification, NotificationKind


class NotifierPort(ABC):
    name: str = "notifier"

    @abstractmethod
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
        """1人に届ける。"""

    @abstractmethod
    async def broadcast(
        self,
        *,
        layer_ids: list[str],
        message: str,
        kind: NotificationKind = NotificationKind.INFO,
        awase_id: str | None = None,
    ) -> list[Notification]:
        """合わせメンバー全員に届ける。返すのは作成できた通知。"""

    @abstractmethod
    async def inbox(self, layer_id: str, *, unread_only: bool = False) -> list[Notification]:
        """お知らせ一覧を新しい順で返す。"""

    @abstractmethod
    async def mark_read(self, layer_id: str, notification_ids: list[str]) -> int:
        """既読にする。既読化できた件数を返す。"""
