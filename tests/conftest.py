"""テスト共通の土台。

認証は開発用ログイン（DevAuth）で通す。実運用の Firebase Authentication は
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

    def __init__(self, client: TestClient, handle: str) -> None:
        self.client = client
        self.handle = handle
        token = client.post("/api/auth/dev-login", json={"handle": handle}).json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.layer = client.post(
            "/api/auth/session", json={"handle": handle}, headers=self.headers
        ).json()
        self.layer_id = self.layer["layer_id"]

    def get(self, path: str, **kwargs):
        return self.client.get(path, headers=self.headers, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(path, headers=self.headers, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.client.patch(path, headers=self.headers, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _use_memory_repository():
    """ユニットテストは必ずインメモリで回す。

    既定の保存先は Firestore だが、ここは速さとテスト間の独立を優先する。
    環境変数の指定漏れで実データベースを触りにいかないよう、明示的に固定する。
    Firestore アダプタ自体は tests/test_firestore.py がエミュレータで検証する。
    """
    settings = get_settings()
    original = settings.repository
    settings.repository = "memory"
    yield
    settings.repository = original


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
    def _login(handle: str = "テストレイヤー") -> Session:
        return Session(client, handle)

    return _login


@pytest.fixture
def user(login) -> Session:
    return login("テストレイヤー")
