"""Firebase Authentication 実装。

ログイン画面は自作で、フロントは Identity Toolkit の REST API を直接叩いて
ID トークンを得る（web API キーは公開前提の値）。バックエンドはそのトークンを
firebase-admin で検証するだけで、パスワードには一切触れない。

この層から上へ渡すのは uid だけ。メールアドレスは Firebase 側に留め、
Firestore には保存しない（設計書 §7-1）。
"""

from __future__ import annotations

import logging

from app.ports.auth import AuthError, AuthIdentity, AuthPort

logger = logging.getLogger(__name__)

# フロントがログイン画面から直接呼ぶ REST エンドポイント（参考値）
SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
SIGN_UP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp"


class FirebaseAuth(AuthPort):
    name = "auth:firebase"

    def __init__(self, project_id: str, web_api_key: str) -> None:
        self.project_id = project_id
        self.web_api_key = web_api_key
        self._auth = self._init_admin()

    def _init_admin(self):
        """firebase-admin を遅延初期化する。

        Cloud Run 上ではサービスアカウントの既定資格情報が使われるため、
        鍵ファイルの持ち回りは不要。
        """
        import firebase_admin
        from firebase_admin import auth as firebase_auth_module

        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={"projectId": self.project_id})
        return firebase_auth_module

    async def verify(self, token: str) -> AuthIdentity:
        import asyncio

        try:
            # 検証は署名・発行者・有効期限をまとめて見る同期API。スレッドへ逃がす
            decoded = await asyncio.to_thread(self._auth.verify_id_token, token)
        except Exception as exc:  # firebase_admin は多様な例外を投げる
            logger.warning("firebase token verification failed: %s", type(exc).__name__)
            raise AuthError("ログイン情報が無効です。再度ログインしてください") from exc

        uid = decoded.get("uid") or decoded.get("sub")
        if not uid:
            raise AuthError("トークンに uid がありません")

        # name はユーザーが自分で付けた表示名。メールは意図的に読まない
        return AuthIdentity(
            uid=str(uid),
            provider="firebase",
            suggested_handle=decoded.get("name"),
        )

    def client_config(self) -> dict:
        return {
            "provider": "firebase",
            "dev_login": False,
            "api_key": self.web_api_key,  # 公開前提の値
            "project_id": self.project_id,
            "sign_in_url": SIGN_IN_URL,
            "sign_up_url": SIGN_UP_URL,
        }
