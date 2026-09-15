"""認証のポート。

ログイン画面は自前で作るが、資格情報の保管とトークン発行は認証基盤に任せる
（既定は Firebase Authentication）。この層が返すのは不透明な uid だけで、
メールアドレスなどの個人情報は上位に渡さない（設計書 §7-1）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class AuthIdentity(BaseModel):
    """検証済みトークンから取り出した、アプリが知ってよい最小限。"""

    uid: str
    provider: str
    # ゲスト（Firebase の匿名ログイン）。相談とプランは使えるが、お気に入りは使えない
    anonymous: bool = False


class AuthError(Exception):
    """トークンが無効・期限切れ・改竄されている。"""


class AuthPort(ABC):
    name: str = "auth"

    @abstractmethod
    async def verify(self, token: str) -> AuthIdentity:
        """ID トークンを検証して身元を返す。失敗時は AuthError。"""

    @abstractmethod
    def client_config(self) -> dict:
        """フロントがログイン画面を組むのに要る公開情報。

        Firebase なら web API キーとログインの REST の URL（公開前提の値のみ）。
        """
