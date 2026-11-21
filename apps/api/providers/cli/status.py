"""Detect whether each local CLI is installed and authenticated."""

import asyncio
from dataclasses import dataclass

from core.config import get_settings
from providers.cli.base import running_in_container
from providers.cli.claude import ClaudeCLIProvider
from providers.cli.codex import CodexCLIProvider
from providers.cli.opencode import OpenCodeCLIProvider

# (installed probe, login probe). Login probes are read-only and never print
# credentials into our logs or API responses.
_PROBES: dict[str, tuple[list[str], list[str]]] = {
    "codex": (["codex", "--version"], ["codex", "login", "status"]),
    "opencode": (["opencode", "--version"], ["opencode", "auth", "list"]),
    "claude": (["claude", "--version"], ["claude", "auth", "status"]),
}


@dataclass(frozen=True)
class CLIToolStatus:
    installed: bool
    logged_in: bool
    detail: str


@dataclass(frozen=True)
class CLIStatus:
    enabled: bool
    in_container: bool
    tools: dict[str, CLIToolStatus]


async def _probe(command: list[str]) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        return process.returncode or 0, stdout.decode(errors="replace")[:500]
    except (TimeoutError, FileNotFoundError, OSError):
        return 127, ""


async def cli_status() -> CLIStatus:
    settings = get_settings()
    enabled = settings.enable_cli_providers and not running_in_container()
    if not enabled:
        reason = (
            "ENABLE_CLI_PROVIDERS is not enabled"
            if not settings.enable_cli_providers
            else "backend is running in a container"
        )
        return CLIStatus(
            enabled=False,
            in_container=running_in_container(),
            tools={
                provider_class.name: CLIToolStatus(False, False, reason)
                for provider_class in (
                    CodexCLIProvider,
                    OpenCodeCLIProvider,
                    ClaudeCLIProvider,
                )
            },
        )

    tools: dict[str, CLIToolStatus] = {}
    for provider_class in (CodexCLIProvider, OpenCodeCLIProvider, ClaudeCLIProvider):
        name = provider_class.executable
        installed_argv, login_argv = _PROBES[name]
        code, output = await _probe(installed_argv)
        installed = code == 0
        if not installed:
            tools[provider_class.name] = CLIToolStatus(
                False, False, f"{name} not installed"
            )
            continue
        code, login_output = await _probe(login_argv)
        # All three login probes exit 0 when credentials are present.
        logged_in = code == 0
        detail = "ok" if logged_in else f"{name} is not logged in"
        # Never surface raw probe output (it may contain account details).
        del output, login_output
        tools[provider_class.name] = CLIToolStatus(True, logged_in, detail)
    return CLIStatus(enabled=True, in_container=False, tools=tools)
