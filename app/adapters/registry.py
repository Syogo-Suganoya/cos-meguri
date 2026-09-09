"""設定に応じてアダプタを組み立てる（設計書 §8 の差し替えスイッチ）。

live を指定してもキーが無ければ mock に落として起動を続ける。
デモ当日に「キーが1本無いだけで全部落ちる」ことを避けるための方針。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.adapters.dev_auth import DevAuth
from app.adapters.in_app_notifier import InAppNotifier
from app.adapters.memory_repo import MemoryRepository
from app.adapters.mock_transit import MockTransit
from app.adapters.mock_vto import MockVto
from app.adapters.stub_llm import StubLlm
from app.config import Settings, get_settings
from app.ports.auth import AuthPort
from app.ports.llm import LlmPort
from app.ports.notifier import NotifierPort
from app.ports.repository import RepositoryPort
from app.ports.transit import TransitPort
from app.ports.vto import VtoPort

logger = logging.getLogger(__name__)


def _demote(mode_var: str, missing: str) -> None:
    logger.warning("%s=live ですが %s が未設定のため mock で起動します", mode_var, missing)


def build_vto(settings: Settings) -> VtoPort:
    if settings.youcam_mode == "live":
        if not settings.youcam_api_key:
            _demote("YOUCAM_MODE", "YOUCAM_API_KEY")
            return MockVto()
        from app.adapters.youcam_vto import YouCamVto

        return YouCamVto(settings.youcam_api_key, settings.youcam_secret_key)
    return MockVto()


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
    """既定は Firebase Authentication。設定が無ければ開発用ログインに落ちる。"""
    if settings.auth_mode == "firebase":
        if not settings.firebase_project_id or not settings.firebase_web_api_key:
            _demote("auth", "FIREBASE_PROJECT_ID / FIREBASE_WEB_API_KEY")
            return DevAuth(settings.dev_auth_secret)
        from app.adapters.firebase_auth import FirebaseAuth

        return FirebaseAuth(settings.firebase_project_id, settings.firebase_web_api_key)

    if not settings.is_local:
        # パスワードを検証しない実装が本番で動かないよう、ここで止める
        raise RuntimeError(
            "AUTH_MODE=dev はローカル専用です。APP_ENV が local/test 以外のときは "
            "AUTH_MODE=firebase と FIREBASE_PROJECT_ID / FIREBASE_WEB_API_KEY を設定してください"
        )
    return DevAuth(settings.dev_auth_secret)


class Adapters:
    """1リクエストを跨いで共有する依存の束。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.vto = build_vto(settings)
        self.transit = build_transit(settings)
        self.llm = build_llm(settings)
        self.repository = build_repository(settings)
        # 通知はアプリ内で完結するので差し替え先が無い。保存先だけが変わる
        self.notifier = InAppNotifier(self.repository)
        self.auth = build_auth(settings)

    def describe(self) -> dict[str, str]:
        return {
            "youcam": self.vto.name,
            "ekispert": self.transit.name,
            "gemini": self.llm.name,
            "notifier": self.notifier.name,
            "repository": self.repository.name,
            "auth": self.auth.name,
        }


@lru_cache
def get_adapters() -> Adapters:
    return Adapters(get_settings())
