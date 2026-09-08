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

    # プロバイダ切り替え
    vto_mode: Mode = "mock"  # YouCam（試着・肌タイプ・顔属性）
    transit_mode: Mode = "mock"  # 駅すぱあと MCP
    llm_mode: Mode = "mock"  # Gemini
    # データは Firestore に置く。memory はテスト専用（プロセスが死ぬと消える）
    repository: Literal["memory", "firestore"] = "firestore"

    # 認証。dev はパスワードを検証しないので、ローカル以外では使わない
    auth_mode: Literal["dev", "firebase"] = "dev"
    firebase_project_id: str = ""
    firebase_web_api_key: str = ""
    # HS256 の推奨長（32バイト以上）を満たす既定値。開発用なので公開されていてよい
    dev_auth_secret: str = "cos-meguri-local-development-secret-key-0001"

    @property
    def is_local(self) -> bool:
        """開発用の緩い挙動を許してよい環境か。"""
        return self.app_env in {"local", "test"}

    # 認証情報（live のときだけ必要）
    youcam_api_key: str = ""
    youcam_secret_key: str = ""
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
    # 設計書 §7-3: 位置共有はイベント当日限定、終了 +24h で削除。
    location_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
