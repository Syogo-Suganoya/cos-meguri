"""テスト共通の土台。

認証はテスト用ログイン（DevAuth）で通す。実運用の Firebase Authentication は
検証の入口が違うだけで、ここから先の扱いは同じ。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.adapters.registry import get_adapters
from app.api.deps import get_agents
from app.config import get_settings
from app.main import app

DAY = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)


class Session:
    """1人ぶんのログイン済みクライアント。"""

    def __init__(self, client: TestClient, user: str, *, anonymous: bool = False) -> None:
        self.client = client
        token = client.post(
            "/api/auth/dev-login", json={"user": user, "anonymous": anonymous}
        ).json()["token"]
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}
        self.layer = client.post("/api/auth/session", headers=self.headers).json()
        self.layer_id = self.layer["layer_id"]

    def get(self, path: str, **kwargs):
        return self.client.get(path, headers=self.headers, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(path, headers=self.headers, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.client.patch(path, headers=self.headers, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.client.delete(path, headers=self.headers, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _use_memory_repository():
    """ユニットテストは必ずインメモリで回す。

    既定の保存先は Firestore だが、ここは速さとテスト間の独立を優先する。
    環境変数の指定漏れで実データベースを触りにいかないよう、明示的に固定する。
    Firestore アダプタ自体は tests/test_firestore.py がエミュレータで検証する。
    """
    settings = get_settings()
    original = (settings.repository, settings.auth_mode)
    settings.repository = "memory"
    # ログインはテスト用の実装で通す。認証エミュレータを立てずに API を回すため
    settings.auth_mode = "dev"
    yield
    settings.repository, settings.auth_mode = original


@pytest.fixture
def client():
    # モジュールキャッシュされたアダプタを毎回作り直し、テスト間の汚染を断つ
    get_adapters.cache_clear()
    get_agents.cache_clear()
    with TestClient(app) as c:
        yield c
    get_adapters.cache_clear()
    get_agents.cache_clear()


@pytest.fixture
def login(client):
    def _login(user: str = "テストレイヤー", *, anonymous: bool = False) -> Session:
        return Session(client, user, anonymous=anonymous)

    return _login


@pytest.fixture
def user(login) -> Session:
    return login("テストレイヤー")


@pytest.fixture
def guest(login) -> Session:
    """ログインしていない人（Firebase の匿名ログインにあたる）。"""
    return login("通りすがり", anonymous=True)
