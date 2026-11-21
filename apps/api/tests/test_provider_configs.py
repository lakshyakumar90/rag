"""Tests for BYOK encryption, SSRF guard, CRUD and connection testing."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.crypto import (
    EncryptionUnavailableError,
    decrypt_secret,
    encrypt_secret,
    key_last4,
)
from core.net import UnsafeBaseURLError, validate_base_url
from models import ProviderConfig
from providers.llm import ChatMessage, Completion, Usage
from providers.llm import registry as llm_registry

PASSWORD = "StrongPassw0rd!"
SECRET = "sk-super-secret-key-1234"


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create(client: AsyncClient, headers: dict[str, str], **overrides):
    payload = {
        "provider_type": "openai",
        "base_url": "https://api.example.com/v1",
        "model": "test-model",
        "api_key": SECRET,
    }
    payload.update(overrides)
    return client.post("/api/v1/provider-configs", headers=headers, json=payload)


def test_crypto_roundtrip_and_last4(master_key) -> None:
    token = encrypt_secret(SECRET)
    assert token != SECRET
    assert decrypt_secret(token) == SECRET
    assert key_last4(SECRET) == "1234"


def test_crypto_requires_master_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_master_key", None)
    with pytest.raises(EncryptionUnavailableError):
        encrypt_secret(SECRET)


def test_crypto_rejects_tampering_and_wrong_key(master_key, monkeypatch) -> None:
    token = encrypt_secret(SECRET)
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(EncryptionUnavailableError, match="could not be decrypted"):
        decrypt_secret(tampered)

    from cryptography.fernet import Fernet

    other_key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "llm_master_key", other_key)
    with pytest.raises(EncryptionUnavailableError):
        decrypt_secret(token)


def test_crypto_rejects_malformed_master_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_master_key", "not-a-fernet-key")
    with pytest.raises(EncryptionUnavailableError, match="not a valid"):
        encrypt_secret(SECRET)


def test_crypto_handles_empty_and_unicode_values(master_key) -> None:
    for value in ("", "café-密钥-🔑", "  leading and trailing  "):
        assert decrypt_secret(encrypt_secret(value)) == value
    assert key_last4("") == ""


def test_base_url_validation(monkeypatch) -> None:
    assert (
        validate_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    )
    for bad in (
        "http://localhost:11434",
        "http://127.0.0.1:8000",
        "http://10.0.0.5/v1",
        "http://192.168.1.2",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com",
        "https://user:pass@example.com",
    ):
        with pytest.raises(UnsafeBaseURLError):
            validate_base_url(bad)

    monkeypatch.setattr(get_settings(), "local_mode_enabled", True)
    assert validate_base_url("http://localhost:11434") == "http://localhost:11434"


async def test_crud_never_returns_keys(
    client: AsyncClient,
    master_key,
    session_factory: async_sessionmaker[AsyncSession],
    caplog,
) -> None:
    headers = await _login(client, "owner@example.com")
    created = await _create(client, headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["key_last4"] == "1234"
    assert "api_key" not in body and "encrypted_api_key" not in body
    config_id = body["id"]

    async with session_factory() as session:
        stored = (await session.execute(select(ProviderConfig))).scalar_one()
        assert stored.encrypted_api_key != SECRET
        assert SECRET not in stored.encrypted_api_key

    listed = await client.get("/api/v1/provider-configs", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [config_id]
    assert all("api_key" not in item for item in listed.json())

    fetched = await client.get(f"/api/v1/provider-configs/{config_id}", headers=headers)
    assert fetched.status_code == 200
    assert "api_key" not in fetched.json()

    rotated = await client.patch(
        f"/api/v1/provider-configs/{config_id}",
        headers=headers,
        json={"api_key": "another-secret-9999", "model": "new-model"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["key_last4"] == "9999"
    assert rotated.json()["model"] == "new-model"

    deleted = await client.delete(
        f"/api/v1/provider-configs/{config_id}", headers=headers
    )
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/provider-configs", headers=headers)).json() == []

    assert SECRET not in caplog.text


async def test_private_base_url_rejected(client: AsyncClient, master_key) -> None:
    headers = await _login(client, "owner@example.com")
    response = await _create(client, headers, base_url="http://10.0.0.5/v1")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSAFE_BASE_URL"


async def test_cross_user_access_denied(client: AsyncClient, master_key) -> None:
    a = await _login(client, "a@example.com")
    b = await _login(client, "b@example.com")
    config_id = (await _create(client, a)).json()["id"]

    url = f"/api/v1/provider-configs/{config_id}"
    responses = (
        await client.get(url, headers=b),
        await client.patch(url, headers=b, json={"model": "stolen"}),
        await client.delete(url, headers=b),
        await client.post(f"{url}/test", headers=b),
    )
    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PROVIDER_CONFIG_NOT_FOUND"


async def test_test_connection_success(
    client: AsyncClient, master_key, monkeypatch
) -> None:
    class FakeProvider:
        name = "openai"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def complete(self, messages, **opts):
            assert messages == [ChatMessage("user", "Reply with OK")]
            return Completion("OK", "stop", Usage(1, 1))

        async def close(self):
            return None

    monkeypatch.setitem(llm_registry._registry, "openai", FakeProvider)
    headers = await _login(client, "owner@example.com")
    config_id = (await _create(client, headers)).json()["id"]

    response = await client.post(
        f"/api/v1/provider-configs/{config_id}/test", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["latency_ms"] >= 0


async def test_test_connection_sanitizes_errors(
    client: AsyncClient, master_key, monkeypatch
) -> None:
    class FailingProvider:
        name = "openai"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def complete(self, messages, **opts):
            raise RuntimeError(f"bad key: {self.kwargs.get('api_key')}")

        async def close(self):
            return None

    monkeypatch.setitem(llm_registry._registry, "openai", FailingProvider)
    headers = await _login(client, "owner@example.com")
    config_id = (await _create(client, headers)).json()["id"]

    response = await client.post(
        f"/api/v1/provider-configs/{config_id}/test", headers=headers
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "CONNECTION_TEST_FAILED"
    assert SECRET not in response.text
