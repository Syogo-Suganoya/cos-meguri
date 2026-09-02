"""開発用ログイン。Firebase の設定が無くてもアプリを通しで動かすための実装。

コス名を入れるだけで短命の JWT を発行する。**パスワードを検証しない**ので
本番では絶対に使わない。registry がローカル以外で live を要求されたときに
これへ落ちないよう、config 側で明示的に選ばせている。

自前で持つのは HMAC の署名鍵だけで、資格情報は保管しない。
"""

from __future__ import annotations

import time
import uuid

import jwt

from app.ports.auth import AuthError, AuthIdentity, AuthPort

ALGORITHM = "HS256"
ISSUER = "cos-meguri-dev"


class DevAuth(AuthPort):
    name = "auth:dev"

    def __init__(self, secret: str, ttl_seconds: int = 60 * 60 * 12) -> None:
        self.secret = secret
        self.ttl_seconds = ttl_seconds

    def issue(self, handle: str, *, uid: str | None = None) -> dict:
        """コス名から開発用トークンを発行する。"""
        if not handle.strip():
            raise AuthError("コス名を入力してください")
        now = int(time.time())
        # 同じコス名なら同じ uid になるようにして、再ログインで別人にならないようにする
        subject = uid or f"dev_{uuid.uuid5(uuid.NAMESPACE_OID, handle).hex[:12]}"
        payload = {
            "iss": ISSUER,
            "sub": subject,
            "handle": handle,
            "iat": now,
            "exp": now + self.ttl_seconds,
        }
        return {
            "token": jwt.encode(payload, self.secret, algorithm=ALGORITHM),
            "expires_in": self.ttl_seconds,
        }

    async def verify(self, token: str) -> AuthIdentity:
        try:
            payload = jwt.decode(
                token, self.secret, algorithms=[ALGORITHM], issuer=ISSUER
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"開発トークンが無効です: {exc}") from exc

        return AuthIdentity(
            uid=str(payload["sub"]),
            provider="dev",
            suggested_handle=payload.get("handle"),
        )

    def client_config(self) -> dict:
        return {
            "provider": "dev",
            "dev_login": True,
            # 画面に警告を出すためのフラグ。パスワード検証をしていないことを隠さない
            "warning": "開発用ログインです（パスワード検証なし）。本番では Firebase Authentication を使います。",
        }
