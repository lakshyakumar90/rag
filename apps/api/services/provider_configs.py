"""BYOK provider configuration business logic."""

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.crypto import (
    EncryptionUnavailableError as CryptoUnavailableError,
)
from core.crypto import decrypt_secret, encrypt_secret, key_last4
from core.net import UnsafeBaseURLError as UnsafeURLError
from core.net import validate_base_url
from models import ProviderConfig, User
from providers.llm import (
    ChatMessage,
    OllamaLLMProvider,
    create_llm_provider,
)
from repositories import ProviderConfigRepository
from schemas import (
    ConnectionTestResponse,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
)
from services.audit import record as record_audit
from services.exceptions import (
    ConnectionTestError,
    EncryptionUnavailableError,
    ProviderConfigNotFoundError,
    UnsafeBaseURLError,
)


class ProviderConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._configs = ProviderConfigRepository(session)

    async def create(
        self, user: User, payload: ProviderConfigCreate
    ) -> ProviderConfigResponse:
        base_url = self._checked_base_url(payload.base_url)
        config = ProviderConfig(
            user_id=user.id,
            provider_type=payload.provider_type,
            base_url=base_url,
            model=payload.model,
            encrypted_api_key=self._encrypt(payload.api_key),
            key_last4=key_last4(payload.api_key),
        )
        await self._configs.add(config)
        await record_audit(
            self._session,
            user,
            "api_key.added",
            target_type="provider_config",
            target_id=config.id,
            details={"provider": str(payload.provider_type)},
        )
        await self._session.commit()
        return ProviderConfigResponse.model_validate(config)

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProviderConfigResponse]:
        configs = await self._configs.list_for_user(user_id)
        return [ProviderConfigResponse.model_validate(config) for config in configs]

    async def get(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ProviderConfigResponse:
        return ProviderConfigResponse.model_validate(
            await self._owned(user_id, config_id)
        )

    async def update(
        self,
        user_id: uuid.UUID,
        config_id: uuid.UUID,
        payload: ProviderConfigUpdate,
    ) -> ProviderConfigResponse:
        config = await self._owned(user_id, config_id)
        changes = payload.model_dump(exclude_unset=True)
        if "base_url" in changes:
            changes["base_url"] = self._checked_base_url(changes["base_url"])
        if changes.get("api_key") is not None:
            secret = changes.pop("api_key")
            config.encrypted_api_key = self._encrypt(secret)
            config.key_last4 = key_last4(secret)
        else:
            changes.pop("api_key", None)
        for field, value in changes.items():
            setattr(config, field, value)
        if "api_key" in payload.model_dump(exclude_unset=True):
            actor = await self._session.get(User, user_id)
            assert actor is not None
            await record_audit(
                self._session,
                actor,
                "api_key.rotated",
                target_type="provider_config",
                target_id=config.id,
            )
        await self._session.commit()
        # updated_at is expired by the flush (onupdate=func.now()).
        await self._session.refresh(config)
        return ProviderConfigResponse.model_validate(config)

    async def delete(self, user_id: uuid.UUID, config_id: uuid.UUID) -> None:
        config = await self._owned(user_id, config_id)
        actor = await self._session.get(User, user_id)
        assert actor is not None
        await record_audit(
            self._session,
            actor,
            "api_key.removed",
            target_type="provider_config",
            target_id=config_id,
            details={"provider": str(config.provider_type)},
        )
        await self._configs.delete(config)
        await self._session.commit()

    async def test_connection(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ConnectionTestResponse:
        config = await self._owned(user_id, config_id)
        secret = self._decrypt(config.encrypted_api_key)
        provider = self._build_provider(config, secret)
        started = time.monotonic()
        try:
            await provider.complete(
                [ChatMessage(role="user", content="Reply with OK")], max_tokens=1
            )
        except Exception as exc:
            raise ConnectionTestError(self._sanitize(str(exc), secret)) from None
        finally:
            close = getattr(provider, "close", None)
            if close:
                await close()
        return ConnectionTestResponse(
            ok=True,
            message="Connection successful",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    # ---------- helpers ----------

    async def _owned(self, user_id: uuid.UUID, config_id: uuid.UUID) -> ProviderConfig:
        config = await self._configs.get(user_id, config_id)
        if config is None:
            raise ProviderConfigNotFoundError()
        return config

    @staticmethod
    def _checked_base_url(base_url: str | None) -> str | None:
        if base_url is None:
            return None
        try:
            return validate_base_url(base_url)
        except UnsafeURLError as exc:
            raise UnsafeBaseURLError(str(exc)) from None

    @staticmethod
    def _encrypt(secret: str) -> str:
        try:
            return encrypt_secret(secret)
        except CryptoUnavailableError as exc:
            raise EncryptionUnavailableError(str(exc)) from None

    @staticmethod
    def _decrypt(token: str) -> str:
        try:
            return decrypt_secret(token)
        except CryptoUnavailableError as exc:
            raise EncryptionUnavailableError(str(exc)) from None

    @staticmethod
    def _sanitize(message: str, secret: str) -> str:
        """Never echo a key back through an error response or log."""
        return message.replace(secret, "***")[:300]

    @staticmethod
    def _build_provider(config: ProviderConfig, secret: str):
        if config.provider_type == "ollama":
            settings = get_settings().model_copy(
                update={
                    "ollama_base_url": config.base_url
                    or get_settings().ollama_base_url,
                    "ollama_llm_model": config.model or get_settings().ollama_llm_model,
                }
            )
            return OllamaLLMProvider(settings=settings)

        opts: dict[str, object] = {"api_key": secret}
        if config.base_url:
            opts["base_url"] = config.base_url
        if config.model:
            opts["model"] = config.model
        return create_llm_provider(config.provider_type, **opts)
