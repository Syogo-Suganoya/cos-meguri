"""Firebase Authentication 実装。ローカルは同じコードのままエミュレータに繋ぐ。

ログイン画面は自作で、フロントは Identity Toolkit の REST API を直接叩いて
ID トークンを得る（web API キーは公開前提の値）。バックエンドはそのトークンを
firebase-admin で検証するだけで、パスワードには一切触れない。

この層から上へ渡すのは uid だけ。メールアドレスは Firebase 側に留め、
Firestore には保存しない（設計書 §7-1）。
"""

from __future__ import annotations

import logging
import os

from app.ports.auth import AuthError, AuthIdentity, AuthPort

logger = logging.getLogger(__name__)

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com"
SIGN_IN_PATH = "/v1/accounts:signInWithPassword"
SIGN_UP_PATH = "/v1/accounts:signUp"
SECURE_TOKEN = "https://securetoken.googleapis.com"
REFRESH_PATH = "/v1/token"


class FirebaseAuth(AuthPort):
    name = "auth:firebase"

    def __init__(
        self,
        project_id: str,
        web_api_key: str,
        *,
        emulator_host: str = "",
        emulator_url: str = "",
    ) -> None:
        self.project_id = project_id
        self.web_api_key = web_api_key
        self.emulator_host = emulator_host
        # ブラウザから見たエミュレータ。コンテナ内の名前（firebase-auth:9099）では届かない
        self.emulator_url = (emulator_url or f"http://{emulator_host}").rstrip("/")
        if emulator_host:
            self.name = "auth:firebase-emulator"
            # firebase-admin は設定ではなく環境変数を読む。.env 経由の値もここで渡す
            os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = emulator_host
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
        # メールは意図的に読まない。読むのはログインの種類（匿名かどうか）だけ
        anonymous = (decoded.get("firebase") or {}).get("sign_in_provider") == "anonymous"
        return AuthIdentity(uid=str(uid), provider="firebase", anonymous=anonymous)

    def client_config(self) -> dict:
        # エミュレータは本番と同じパスを、自分のホストの下にぶら下げて受ける
        base = (
            f"{self.emulator_url}/identitytoolkit.googleapis.com"
            if self.emulator_host
            else IDENTITY_TOOLKIT
        )
        token_base = (
            f"{self.emulator_url}/securetoken.googleapis.com" if self.emulator_host else SECURE_TOKEN
        )
        return {
            "provider": "firebase",
            "emulator": bool(self.emulator_host),
            "api_key": self.web_api_key,  # 公開前提の値
            "project_id": self.project_id,
            "sign_in_url": base + SIGN_IN_PATH,
            # メールとパスワードを付けずに叩くと、ゲスト（匿名）の通行証が出る
            "sign_up_url": base + SIGN_UP_PATH,
            # ID トークンは1時間で切れる。ゲストは入り直す手段が無いので、ここで更新する
            "refresh_url": token_base + REFRESH_PATH,
        }
