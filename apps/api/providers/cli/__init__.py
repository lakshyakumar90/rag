"""Local-only CLI providers (experimental, disabled by default)."""

from providers.cli.base import CLIProvider, CLIProvidersDisabledError, build_prompt
from providers.cli.claude import ClaudeCLIProvider
from providers.cli.codex import CodexCLIProvider
from providers.cli.opencode import OpenCodeCLIProvider
from providers.cli.registry import available_cli_providers, create_cli_provider
from providers.cli.status import CLIStatus, CLIToolStatus, cli_status

__all__ = [
    "CLIProvider",
    "CLIProvidersDisabledError",
    "CLIStatus",
    "CLIToolStatus",
    "ClaudeCLIProvider",
    "CodexCLIProvider",
    "OpenCodeCLIProvider",
    "available_cli_providers",
    "build_prompt",
    "cli_status",
    "create_cli_provider",
]
