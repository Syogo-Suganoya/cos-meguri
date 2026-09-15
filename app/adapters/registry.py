"""設定に応じてアダプタを組み立てる（設計書 §8 の差し替えスイッチ）。

live を指定してもキーが無ければ mock に落として起動を続ける。
デモ当日に「キーが1本無いだけで全部落ちる」ことを避けるための方針。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.adapters.dev_auth import DevAuth
from app.adapters.memory_repo import MemoryRepository
from app.adapters.mock_transit import MockTransit
from app.adapters.stub_llm import StubLlm
from app.config import Settings, get_settings
from app.ports.auth import AuthPort
from app.ports.llm import LlmPort
from app.ports.repository import RepositoryPort
from app.ports.transit import TransitPort

logger = logging.getLogger(__name__)


def _demote(mode_var: str, missing: str) -> None:
    logger.warning("%s=live ですが %s が未設定のため mock で起動します", mode_var, missing)


def build_transit(settings: Settings) -> TransitPort:
    if settings.ekispert_mode == "live":
        if not settings.ekispert_mcp_url:
            _demote("EKISPERT_MODE", "EKISPERT_MCP_URL")
            return MockTransit()
        from app.adapters.ekispert_transit import EkispertTransit

        return EkispertTransit(settings.ekispert_mcp_url, settings.ekispert_api_key)
    return MockTransit()


def build_llm(settings: Settings) -> LlmPort:
    if settings.gemini_mode == "live":
        if not settings.google_api_key:
            _demote("GEMINI_MODE", "GOOGLE_API_KEY")
            return StubLlm()
        from app.adapters.gemini_llm import GeminiLlm

        return GeminiLlm(settings.google_api_key, settings.gemini_model)
    return StubLlm()


def build_repository(settings: Settings) -> RepositoryPort:
    if settings.repository == "firestore":
        from app.adapters.firestore_repo import FirestoreRepository

        return FirestoreRepository(settings.google_cloud_project)
    return MemoryRepository()


def build_auth(settings: Settings) -> AuthPort:
    """ローカルも本番も Firebase Authentication。ローカルはエミュレータに繋ぐ。

    認証だけは mock に落とさない。設定が足りなければ起動を止める。
    黙って「パスワードを確かめないログイン」に落ちると、気づかないまま外に出るため。
    """
    # firebase-admin はこの環境変数があると署名の無いトークンを通す。
    # .env 経由の値も、環境変数としての値も、どちらも本番では許さない
    emulator_host = settings.firebase_auth_emulator_host or os.environ.get(
        "FIREBASE_AUTH_EMULATOR_HOST", ""
    )
    if emulator_host and not settings.is_local:
        raise RuntimeError(
            "FIREBASE_AUTH_EMULATOR_HOST はローカル専用です。設定されていると署名の無い"
            "トークンが通ってしまうので、APP_ENV が local/test 以外では外してください"
        )

    if settings.auth_mode == "dev":
        if not settings.is_test:
            # パスワードを検証しない実装は、テストの中でしか動かさない
            raise RuntimeError(
                "AUTH_MODE=dev はテスト専用です。ローカルは認証エミュレータ"
                "（docker compose up api で一緒に起動する）を使ってください"
            )
        return DevAuth(settings.dev_auth_secret)

    if not settings.firebase_project_id or not settings.firebase_web_api_key:
        raise RuntimeError(
            "AUTH_MODE=firebase には FIREBASE_PROJECT_ID と FIREBASE_WEB_API_KEY が要ります"
        )
    from app.adapters.firebase_auth import FirebaseAuth

    return FirebaseAuth(
        settings.firebase_project_id,
        settings.firebase_web_api_key,
        emulator_host=emulator_host,
        emulator_url=settings.firebase_auth_emulator_url,
    )


class Adapters:
    """1リクエストを跨いで共有する依存の束。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.transit = build_transit(settings)
        self.llm = build_llm(settings)
        self.repository = build_repository(settings)
        self.auth = build_auth(settings)

    def describe(self) -> dict[str, str]:
        return {
            "ekispert": self.transit.name,
            "gemini": self.llm.name,
            "repository": self.repository.name,
            "auth": self.auth.name,
        }


@lru_cache
def get_adapters() -> Adapters:
    return Adapters(get_settings())
