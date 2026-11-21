"""Codex CLI adapter: `codex exec --json` in the read-only sandbox."""

from typing import Any

from providers.cli.base import CLIProvider
from providers.llm.types import (
    Error,
    Finish,
    LLMEvent,
    TextDelta,
    Usage,
)


class CodexCLIProvider(CLIProvider):
    name = "cli-codex"
    executable = "codex"

    def argv(self, prompt: str, opts: dict[str, Any]) -> list[str]:
        # No --full-auto, --approve-for-me or writable sandbox; the read-only
        # sandbox is the default and is repeated here explicitly.
        return [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ignore-user-config",
            prompt,
        ]

    def config_files(self) -> dict[str, str]:
        return {}

    def parse_event(self, event: dict[str, Any]) -> list[LLMEvent]:
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                return [TextDelta(text=str(item["text"]))]
            return []
        if kind == "turn.completed":
            usage = event.get("usage") or {}
            return [
                Usage(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                ),
                Finish(reason="stop"),
            ]
        if kind in ("turn.failed", "error"):
            error = event.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else error
            return [Error(message=str(message or "codex failed"), code=str(kind))]
        return []
