"""OpenCode CLI adapter: `opencode run --format json` with all tools denied."""

import json
from typing import Any

from providers.cli.base import CLIProvider
from providers.llm.types import (
    Error,
    Finish,
    LLMEvent,
    TextDelta,
    Usage,
)

# V2 permissions: deny every action. Text output is not a tool action.
_DENY_ALL = {
    "$schema": "https://opencode.ai/config.json",
    "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
}


class OpenCodeCLIProvider(CLIProvider):
    name = "cli-opencode"
    executable = "opencode"

    def argv(self, prompt: str, opts: dict[str, Any]) -> list[str]:
        # Deliberately no --auto (auto-approve). --standalone avoids the shared
        # background service and its global config/plugins.
        model = opts.get("model") or self._settings.cli_opencode_model
        return [
            "opencode",
            "run",
            "--format",
            "json",
            "--standalone",
            *([f"--model={model}"] if model else []),
            "--",
            prompt,
        ]

    def config_files(self) -> dict[str, str]:
        return {"opencode.json": json.dumps(_DENY_ALL)}

    def parse_event(self, event: dict[str, Any]) -> list[LLMEvent]:
        kind = event.get("type")
        part = event.get("part") or {}
        if kind == "text":
            text = part.get("text") or event.get("text")
            return [TextDelta(text=str(text))] if text else []
        if kind == "step_finish":
            tokens = part.get("tokens") or {}
            return [
                Usage(
                    input_tokens=int(tokens.get("input") or 0),
                    output_tokens=int(tokens.get("output") or 0),
                )
            ]
        if kind == "finish":
            return [Finish(reason="stop")]
        if kind == "error":
            error = event.get("error") or {}
            status = error.get("status") if isinstance(error, dict) else None
            message = {
                401: "OpenCode authentication failed for this model.",
                402: "Insufficient OpenCode credits for this model.",
                403: "OpenCode access was denied for this model.",
                410: "This OpenCode model is no longer available.",
                429: "OpenCode reached the usage limit for this model.",
            }.get(status, "OpenCode could not complete the request.")
            return [Error(message=message, code=str(kind))]
        return []
