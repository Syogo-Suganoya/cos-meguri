"""テスト専用のログイン。Firebase を立てずに API の結合テストを回すための実装。

名前を渡すだけで短命の JWT を発行する。**パスワードを検証しない**ので、
APP_ENV=test 以外では registry が起動を止める。ローカルで画面を触るときは
認証エミュレータを使う。

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

    def issue(self, user: str, *, anonymous: bool = False) -> dict:
        """テスト用の利用者名からトークンを発行する。anonymous はゲスト（匿名ログイン）の再現。"""
        if not user.strip():
            raise AuthError("利用者名を入力してください")
        now = int(time.time())
        # 同じ名前なら同じ uid。テストで「再ログインしても同じ人」を再現する
        prefix = "guest" if anonymous else "dev"
        payload = {
            "iss": ISSUER,
            "sub": f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_OID, user).hex[:12]}",
            "anon": anonymous,
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
            uid=str(payload["sub"]), provider="dev", anonymous=bool(payload.get("anon"))
        )

    def client_config(self) -> dict:
        return {
            "provider": "dev",
            "warning": "テスト用ログインです（パスワード検証なし）。",
        }
