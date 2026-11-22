"""Settings defaults, provider tests and per-conversation overrides."""

import uuid

from httpx import AsyncClient

from providers.llm.types import AuthenticationError
from services.chat import ChatService
from services.workspaces import WorkspaceContext

PASSWORD = "StrongPassw0rd!"


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_defaults_are_saved_and_returned(client: AsyncClient) -> None:
    headers = await _login(client, "settings@example.com")
    first = await client.get("/api/v1/ai/defaults", headers=headers)
    assert first.status_code == 200
    assert first.json()["saved"] is False

    saved = await client.put(
        "/api/v1/ai/defaults",
        headers=headers,
        json={"provider": "ollama", "model": "llama3.2:latest"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "provider": "ollama",
        "model": "llama3.2:latest",
        "saved": True,
    }

    options = await client.get("/api/v1/ai/providers", headers=headers)
    assert options.status_code == 200
    assert options.json()["defaults"]["provider"] == "ollama"
    ids = [item["id"] for item in options.json()["options"]]
    assert {"ollama", "openai", "anthropic", "cli-codex", "cli-opencode"} <= set(ids)


async def test_connection_test_classifies_authentication_error(
    client: AsyncClient, monkeypatch
) -> None:
    headers = await _login(client, "test-connection@example.com")

    class Failing:
        async def complete(self, messages, **opts):
            raise AuthenticationError("bad key for sk-secret-value")

        async def close(self):
            return None

    import services.ai_settings as module

    monkeypatch.setattr(module, "create_llm_provider", lambda name, **opts: Failing())
    response = await client.post(
        "/api/v1/ai/test",
        headers=headers,
        json={"provider": "openai", "model": "gpt-4o-mini"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "authentication"
    assert "sk-secret-value" not in body["detail"]


async def test_conversation_selection_is_persisted(client: AsyncClient) -> None:
    headers = await _login(client, "conversation-selection@example.com")
    workspace = await client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Selection", "slug": "selection"},
    )
    workspace_id = workspace.json()["id"]
    created = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations",
        headers=headers,
        json={"title": "Thread", "provider": "cli-codex", "model": "gpt-6-luna"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    assert created.json()["provider"] == "cli-codex"
    assert created.json()["model"] == "gpt-6-luna"

    updated = await client.patch(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/selection",
        headers=headers,
        json={"provider": "ollama", "model": "llama3.2:latest"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["provider"] == "ollama"
    listed = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations", headers=headers
    )
    assert listed.json()[0]["model"] == "llama3.2:latest"


def test_missing_ollama_model_is_classified_as_unsupported() -> None:
    from services.ai_settings import AISettingsService

    status, detail = AISettingsService._classify(
        RuntimeError("Ollama returned HTTP 404")
    )
    assert status == "unsupported_model"
    assert "not available" in detail


async def test_selection_precedence() -> None:
    """Explicit > conversation > Settings > server default."""

    from types import SimpleNamespace

    user = SimpleNamespace(id=uuid.uuid4())

    class Conversation:
        provider = "cli-codex"
        model = "conversation-model"

    service = ChatService(None, None, None)
    context = WorkspaceContext(user=user, workspace=SimpleNamespace(), role="member")
    assert await service._selection(context, None, None, Conversation()) == (
        "cli-codex",
        "conversation-model",
    )
    assert await service._selection(context, "ollama", "explicit", Conversation()) == (
        "ollama",
        "explicit",
    )
