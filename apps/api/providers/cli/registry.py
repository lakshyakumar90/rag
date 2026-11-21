"""Factory for local CLI-backed LLM providers."""

from core.config import get_settings
from providers.cli.base import (
    CLIProvider,
    CLIProvidersDisabledError,
    running_in_container,
)
from providers.cli.claude import ClaudeCLIProvider
from providers.cli.codex import CodexCLIProvider
from providers.cli.opencode import OpenCodeCLIProvider

_CLI_PROVIDERS: dict[str, type[CLIProvider]] = {
    provider.name: provider
    for provider in (CodexCLIProvider, OpenCodeCLIProvider, ClaudeCLIProvider)
}


def available_cli_providers() -> list[str]:
    return sorted(_CLI_PROVIDERS)


def create_cli_provider(name: str) -> CLIProvider:
    """Create a CLI provider, enforcing the feature flag and host requirement."""
    settings = get_settings()
    if not settings.enable_cli_providers:
        raise CLIProvidersDisabledError("ENABLE_CLI_PROVIDERS is not enabled")
    if running_in_container():
        raise CLIProvidersDisabledError(
            "CLI providers require the backend to run on the host"
        )
    try:
        provider_class = _CLI_PROVIDERS[name]
    except KeyError as exc:
        raise CLIProvidersDisabledError(f"unknown CLI provider: {name}") from exc
    return provider_class(settings=settings)
