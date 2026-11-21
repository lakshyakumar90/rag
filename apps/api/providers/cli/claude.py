"""Claude Code CLI adapter: `claude -p --output-format stream-json`, no tools."""

from typing import Any

from providers.cli.base import CLIProvider
from providers.llm.types import (
    Error,
    Finish,
    LLMEvent,
    TextDelta,
    Usage,
)


class ClaudeCLIProvider(CLIProvider):
    name = "cli-claude"
    executable = "claude"

    def argv(self, prompt: str, opts: dict[str, Any]) -> list[str]:
        # No --dangerously-skip-permissions / --allow-dangerously-skip-permissions.
        # --tools "" removes built-in tools, --disallowedTools "*" removes MCP
        # tools, and --permission-prompts none denies anything that still asks.
        return [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--tools",
            "",
            "--disallowedTools",
            "*",
            "--permission-prompts",
            "none",
            "--no-session-persistence",
            "--strict-mcp-config",
            prompt,
        ]

    def config_files(self) -> dict[str, str]:
        return {}

    def parse_event(self, event: dict[str, Any]) -> list[LLMEvent]:
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message") or {}
            events: list[LLMEvent] = [
                TextDelta(text=str(block["text"]))
                for block in message.get("content", [])
                if isinstance(block, dict)
                and block.get("type") == "text"
                and block.get("text")
            ]
            usage = message.get("usage") or {}
            if usage:
                events.append(
                    Usage(
                        input_tokens=int(usage.get("input_tokens") or 0),
                        output_tokens=int(usage.get("output_tokens") or 0),
                    )
                )
            return events
        if kind == "result":
            if event.get("is_error"):
                return [Error(message=str(event.get("result") or "claude failed"))]
            usage = event.get("usage") or {}
            return [
                Usage(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                ),
                Finish(reason="stop"),
            ]
        if kind == "error":
            return [Error(message=str(event.get("error") or "claude failed"))]
        return []
