"""Settings → AI providers: defaults, discovery and real connection tests."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.net import UnsafeBaseURLError, validate_base_url
from models import ProviderConfig, UserAIDefaults
from providers.cli.status import cli_models, cli_status
from providers.llm.registry import available_providers, create_llm_provider
from providers.llm.types import (
    AuthenticationError,
    ChatMessage,
    ContextLengthError,
    LLMProviderError,
    ProviderAPIError,
    RateLimitError,
    UnknownProviderError,
)
from schemas import (
    AIDefaultsResponse,
    ProviderModelsResponse,
    ProviderOption,
    ProviderOptionsResponse,
    ProviderTestResponse,
    TestStatus,
)
from services.exceptions import DomainError

_BUILTINS = (
    ("ollama", "Ollama (local)", True, True),
    ("openai", "OpenAI", False, True),
    ("openai-compatible", "OpenAI-compatible", True, True),
    ("anthropic", "Anthropic", False, True),
    ("cli-codex", "Codex CLI", True, True),
    ("cli-opencode", "OpenCode CLI", True, True),
    ("cli-claude", "Claude Code CLI", True, False),
)


class ProviderConfigNotFoundError(DomainError):
    status_code = 404
    code = "PROVIDER_CONFIG_NOT_FOUND"
    message = "Provider configuration not found"


class UnsafeBaseURLErrorDomain(DomainError):
    status_code = 400
    code = "UNSAFE_BASE_URL"
    message = "That provider URL is not allowed"


class UnknownProviderDomainError(DomainError):
    status_code = 400
    code = "UNKNOWN_PROVIDER"
    message = "Unknown provider"


def _default_model(provider: str) -> str | None:
    settings = get_settings()
    if provider in ("openai", "openai-compatible"):
        return settings.openai_model
    if provider == "anthropic":
        return settings.anthropic_model
    if provider == "ollama":
        return settings.ollama_llm_model
    if provider == "cli-codex":
        return settings.cli_codex_model
    if provider == "cli-opencode":
        return settings.cli_opencode_model or provider
    return None


class AISettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()

    # ---------- defaults ----------

    async def get_defaults(self, user_id: uuid.UUID) -> AIDefaultsResponse:
        row = (
            await self._session.execute(
                select(UserAIDefaults).where(UserAIDefaults.user_id == user_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return AIDefaultsResponse(
                provider=self._settings.chat_default_provider
                or self._settings.llm_provider,
                model=_default_model(self._settings.llm_provider),
                saved=False,
            )
        return AIDefaultsResponse(provider=row.provider, model=row.model, saved=True)

    async def save_defaults(
        self, user_id: uuid.UUID, provider: str, model: str | None
    ) -> AIDefaultsResponse:
        # Validate the provider name before persisting a default.
        if provider not in available_providers():
            raise UnknownProviderDomainError(f"Unknown provider: {provider}")
        existing = (
            await self._session.execute(
                select(UserAIDefaults).where(UserAIDefaults.user_id == user_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._session.add(
                UserAIDefaults(user_id=user_id, provider=provider, model=model or None)
            )
        else:
            await self._session.execute(
                update(UserAIDefaults)
                .where(UserAIDefaults.user_id == user_id)
                .values(provider=provider, model=model or None)
            )
        await self._session.commit()
        return AIDefaultsResponse(provider=provider, model=model, saved=True)

    async def provider_for(self, user_id: uuid.UUID, name: str) -> Any:
        """Build an LLM provider for a built-in id or a saved BYOK config id."""
        if not name.startswith("config:"):
            return create_llm_provider(name)
        config_id = name.split(":", 1)[1]
        try:
            identifier = uuid.UUID(config_id)
        except ValueError as exc:
            raise ProviderConfigNotFoundError() from exc
        config = (
            await self._session.execute(
                select(ProviderConfig).where(
                    ProviderConfig.id == identifier,
                    ProviderConfig.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if config is None:
            raise ProviderConfigNotFoundError()
        from core.crypto import decrypt_secret

        opts: dict[str, Any] = {"api_key": decrypt_secret(config.encrypted_api_key)}
        if config.base_url:
            opts["base_url"] = validate_base_url(config.base_url)
        if config.model:
            opts["model"] = config.model
        return create_llm_provider(config.provider_type, **opts)

    # ---------- options ----------

    async def options(self, user_id: uuid.UUID) -> ProviderOptionsResponse:
        status = await cli_status() if self._settings.enable_cli_providers else None
        options: list[ProviderOption] = []
        for name, label, discovery, manual in _BUILTINS:
            registered = name in available_providers()
            available = registered
            if name.startswith("cli-"):
                available = bool(
                    status and status.tools.get(name) and status.tools[name].installed
                )
            options.append(
                ProviderOption(
                    id=name,
                    label=label,
                    built_in=True,
                    available=available,
                    discovery=discovery and not name.startswith("cli-claude"),
                    manual_model=manual,
                    default_model=_default_model(name),
                )
            )
        configs = (
            (
                await self._session.execute(
                    select(ProviderConfig).where(ProviderConfig.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        for config in configs:
            options.append(
                ProviderOption(
                    id=f"config:{config.id}",
                    label=f"{config.provider_type} (your key)",
                    built_in=False,
                    available=True,
                    discovery=True,
                    manual_model=True,
                    config_id=str(config.id),
                    default_model=config.model,
                )
            )
        return ProviderOptionsResponse(
            options=options, defaults=await self.get_defaults(user_id)
        )

    # ---------- connection test ----------

    async def test(
        self,
        user_id: uuid.UUID,
        provider: str,
        model: str | None,
        config_id: str | None,
    ) -> ProviderTestResponse:
        name, base_url, key, configured_model, secret = await self._resolve(
            user_id, provider, config_id
        )
        effective_model = model or configured_model or _default_model(name)
        started = time.monotonic()
        instance: Any = None
        try:
            instance = self._build(name, base_url, key)
            # All adapters accept a per-call model; Ollama's constructor does
            # not, so passing it only here works for every provider.
            await instance.complete(
                [ChatMessage(role="user", content="Reply with OK")],
                max_tokens=1,
                model=effective_model,
            )
        except Exception as exc:  # classified below; never leak the secret
            status, detail = self._classify(exc)
            if secret:
                detail = detail.replace(secret, "***")
            return ProviderTestResponse(
                ok=False,
                status=status,
                detail=detail[:300],
                provider=name,
                model=effective_model,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            if instance is not None:
                close = getattr(instance, "close", None)
                if close:
                    await close()
        return ProviderTestResponse(
            ok=True,
            status="success",
            detail="Model responded successfully.",
            provider=name,
            model=effective_model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    # ---------- model discovery ----------

    async def models(
        self, user_id: uuid.UUID, provider: str, config_id: str | None
    ) -> ProviderModelsResponse:
        name, base_url, key, _configured_model, secret = await self._resolve(
            user_id, provider, config_id
        )
        try:
            if name.startswith("cli-"):
                return ProviderModelsResponse(
                    provider=name, models=await cli_models(name)
                )
            if name == "ollama":
                base = base_url or self._settings.ollama_base_url
                data = await self._get_json(f"{base.rstrip('/')}/api/tags")
                return ProviderModelsResponse(
                    provider=name,
                    models=[
                        item["name"]
                        for item in data.get("models", [])
                        if item.get("name")
                    ],
                )
            if name in ("openai", "openai-compatible"):
                base = base_url or self._settings.openai_base_url
                token = key or self._settings.openai_api_key
                data = await self._get_json(
                    f"{base.rstrip('/')}/models",
                    {"Authorization": f"Bearer {token}"} if token else None,
                )
                return ProviderModelsResponse(
                    provider=name,
                    models=[
                        item["id"] for item in data.get("data", []) if item.get("id")
                    ],
                )
            if name == "anthropic":
                base = base_url or self._settings.anthropic_base_url
                token = key or self._settings.anthropic_api_key
                data = await self._get_json(
                    f"{base.rstrip('/')}/models",
                    {"x-api-key": token, "anthropic-version": "2023-06-01"}
                    if token
                    else None,
                )
                return ProviderModelsResponse(
                    provider=name,
                    models=[
                        item["id"] for item in data.get("data", []) if item.get("id")
                    ],
                )
        except Exception as exc:  # noqa: BLE001 - discovery is best effort
            detail = str(exc)
            if secret:
                detail = detail.replace(secret, "***")
            # A failed discovery is not an error: the UI keeps manual entry.
            return ProviderModelsResponse(provider=name, models=[], manual_only=True)
        return ProviderModelsResponse(provider=name, models=[], manual_only=True)

    # ---------- helpers ----------

    async def _resolve(
        self, user_id: uuid.UUID, provider: str, config_id: str | None
    ) -> tuple[str, str | None, str | None, str | None, str | None]:
        if config_id:
            try:
                config_id_uuid = uuid.UUID(config_id)
            except ValueError as exc:
                raise ProviderConfigNotFoundError() from exc
            config = (
                await self._session.execute(
                    select(ProviderConfig).where(
                        ProviderConfig.id == config_id_uuid,
                        ProviderConfig.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if config is None:
                raise ProviderConfigNotFoundError()
            from core.crypto import decrypt_secret

            secret = decrypt_secret(config.encrypted_api_key)
            base_url = config.base_url
            if base_url:
                try:
                    base_url = validate_base_url(base_url)
                except UnsafeBaseURLError as exc:
                    raise UnsafeBaseURLErrorDomain(str(exc)) from exc
            return config.provider_type, base_url, secret, config.model, secret
        if provider.startswith("config:"):
            return await self._resolve(user_id, "", provider.split(":", 1)[1])
        if provider not in available_providers():
            raise UnknownProviderDomainError(f"Unknown provider: {provider}")
        return provider, None, None, None, None

    def _build(
        self,
        name: str,
        base_url: str | None,
        api_key: str | None,
    ) -> Any:
        # Ollama's constructor takes no ``model`` argument; every adapter
        # accepts a per-call ``model`` option instead.
        if name == "ollama" and base_url:
            settings = get_settings().model_copy(update={"ollama_base_url": base_url})
            return create_llm_provider(name, settings=settings)
        opts: dict[str, Any] = {}
        if base_url:
            opts["base_url"] = base_url
        if api_key:
            opts["api_key"] = api_key
        return create_llm_provider(name, **opts)

    @staticmethod
    async def _get_json(url: str, headers: dict[str, str] | None = None) -> dict:
        async with httpx.AsyncClient(
            timeout=10.0, headers=headers or {}, follow_redirects=False
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                raise RuntimeError(f"model discovery failed ({response.status_code})")
            return response.json()

    @staticmethod
    def _classify(exc: Exception) -> tuple[TestStatus, str]:
        if isinstance(exc, AuthenticationError):
            return "authentication", "Authentication failed — check the API key."
        if isinstance(exc, RateLimitError):
            return "quota", "Quota or rate limit reached — check your provider plan."
        if isinstance(exc, ContextLengthError):
            return "invalid_request", "The model rejected the test prompt."
        if isinstance(exc, UnknownProviderError):
            return "unavailable", "That provider is not configured on the server."
        if isinstance(
            exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)
        ):
            return "timeout", "The provider did not respond in time — try again."
        if isinstance(exc, ProviderAPIError):
            code = (exc.code or "").lower()
            message = exc.message.lower()
            if "model" in code or "model" in message or "not found" in message:
                return "unsupported_model", "The selected model is not available."
            if exc.status_code in (401, 403):
                return "authentication", "Authentication failed — check the API key."
            if exc.status_code == 429:
                return "quota", "Quota or rate limit reached — check your plan."
            return "unavailable", f"Provider error: {exc.message}"
        if isinstance(exc, LLMProviderError):
            return "unavailable", "The provider could not be reached."
        message = str(exc)
        if "404" in message or "not found" in message.lower():
            return "unsupported_model", "The selected model is not available."
        return "unavailable", f"Connection failed: {type(exc).__name__}"
