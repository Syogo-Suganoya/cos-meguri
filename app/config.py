"""環境変数だけで mock / live を切り替える（設計書 §8）。

キーが揃っていない開発初期は全て mock で完結し、`.env` にキーを入れた
プロバイダだけが実APIへ差し替わる。実キーはイメージに焼き込まず、
本番は Secret Manager から Cloud Run に注入する。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["mock", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"

    # 外部APIを実際に叩くか、内蔵の代役で済ませるか。変数名は使う API に揃えてある
    ekispert_mode: Mode = "mock"  # 駅すぱあと MCP: 経路
    # GEMINI_MODEL（モデルID）と1文字違い。取り違えると起動時に弾かれる
    gemini_mode: Mode = "mock"  # Gemini: 言い回し・翻訳・補足
    # データは Firestore に置く。memory はテスト専用（プロセスが死ぬと消える）
    repository: Literal["memory", "firestore"] = "firestore"

    # 認証。ローカルも本番も Firebase Authentication（ローカルはエミュレータ）。
    # dev はパスワードを検証しないテスト専用の実装で、APP_ENV=test 以外では起動を止める
    auth_mode: Literal["dev", "firebase"] = "firebase"
    firebase_project_id: str = ""
    firebase_web_api_key: str = ""
    # 認証エミュレータの場所。firebase-admin は FIREBASE_AUTH_EMULATOR_HOST を環境変数から
    # 直接読み、**署名の無いトークンを通すようになる**。本番では絶対に設定しない
    firebase_auth_emulator_host: str = ""
    # ブラウザから見たエミュレータの URL（コンテナの中と外でホスト名が違うため別に持つ）
    firebase_auth_emulator_url: str = ""
    # HS256 の推奨長（32バイト以上）を満たす既定値。テスト用なので公開されていてよい
    dev_auth_secret: str = "cos-meguri-local-development-secret-key-0001"

    @property
    def is_local(self) -> bool:
        """エミュレータに繋いでよい環境か。"""
        return self.app_env in {"local", "test"}

    @property
    def is_test(self) -> bool:
        """パスワードを検証しない実装を許してよい環境か。"""
        return self.app_env == "test"

    # 認証情報（live のときだけ必要）
    ekispert_api_key: str = ""
    ekispert_mcp_url: str = ""
    google_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"

    google_cloud_project: str = "cos-meguri-local"
    firestore_emulator_host: str = ""

    # 既定言語（設計書 §5 多言語。MVPは日英、追加は設定のみ）
    default_lang: str = "ja"

    # 設計書 §7-1: 顔画像は処理後即破棄。保持するのは数値スコアのみ。
    face_image_retention_seconds: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
