"""ログインの組み立ての検証。

ローカルも本番も Firebase Authentication で、ローカルはエミュレータに繋ぐ。
パスワードを確かめない経路と、署名を確かめない経路が、外に出ないことを見る。
"""

from __future__ import annotations

import pytest

from app.adapters.firebase_auth import FirebaseAuth
from app.adapters.registry import build_auth
from app.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "app_env": "local",
        "auth_mode": "firebase",
        "firebase_project_id": "cos-meguri-local",
        "firebase_web_api_key": "local-emulator-key",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture(autouse=True)
def _no_emulator_env(monkeypatch):
    """ホストの環境変数に引きずられないようにする。"""
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)


def test_emulator_is_refused_outside_local():
    """エミュレータの設定があると、firebase-admin は署名の無いトークンを通す。"""
    with pytest.raises(RuntimeError, match="FIREBASE_AUTH_EMULATOR_HOST"):
        build_auth(_settings(app_env="production", firebase_auth_emulator_host="firebase-auth:9099"))


def test_emulator_env_var_alone_is_also_refused_outside_local(monkeypatch):
    """設定を経由せず環境変数だけが残っていても止める。"""
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "firebase-auth:9099")
    with pytest.raises(RuntimeError, match="FIREBASE_AUTH_EMULATOR_HOST"):
        build_auth(_settings(app_env="production"))


def test_password_less_login_is_test_only():
    """ローカルで画面を触るときも、パスワードを確かめるログインを通す。"""
    with pytest.raises(RuntimeError, match="テスト専用"):
        build_auth(_settings(auth_mode="dev"))
    assert build_auth(_settings(app_env="test", auth_mode="dev")).name == "auth:dev"


def test_missing_firebase_settings_stop_the_start_instead_of_falling_back():
    with pytest.raises(RuntimeError, match="FIREBASE_PROJECT_ID"):
        build_auth(_settings(firebase_web_api_key=""))


def test_browser_is_pointed_at_the_emulator_by_its_public_url(monkeypatch):
    """コンテナの中の名前（firebase-auth）はブラウザから引けない。"""
    auth = FirebaseAuth(
        "cos-meguri-local",
        "local-emulator-key",
        emulator_host="firebase-auth:9099",
        emulator_url="http://localhost:9099",
    )
    config = auth.client_config()
    assert config["emulator"] is True
    assert config["sign_in_url"] == (
        "http://localhost:9099/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    )
    assert auth.name == "auth:firebase-emulator"


def test_production_talks_to_the_real_identity_toolkit():
    config = FirebaseAuth("cos-meguri", "key").client_config()
    assert config["emulator"] is False
    assert config["sign_up_url"] == "https://identitytoolkit.googleapis.com/v1/accounts:signUp"


def test_browser_refreshes_tokens_at_the_emulator_too():
    """ゲストは入り直す手段が無い。1時間で切れる通行証を、同じ相手で更新する。"""
    local = FirebaseAuth("p", "k", emulator_host="firebase-auth:9099", emulator_url="http://localhost:9099")
    assert local.client_config()["refresh_url"] == "http://localhost:9099/securetoken.googleapis.com/v1/token"
    assert FirebaseAuth("p", "k").client_config()["refresh_url"] == "https://securetoken.googleapis.com/v1/token"


@pytest.mark.parametrize("provider,anonymous", [("anonymous", True), ("password", False)])
async def test_firebase_tells_guests_apart_by_sign_in_provider(provider, anonymous):
    auth = FirebaseAuth("p", "k")
    decoded = {"uid": "u1", "email": "a@example.com", "firebase": {"sign_in_provider": provider}}
    auth._auth = type("Stub", (), {"verify_id_token": staticmethod(lambda token: decoded)})
    identity = await auth.verify("token")
    assert identity.anonymous is anonymous
    assert "email" not in identity.model_dump()
