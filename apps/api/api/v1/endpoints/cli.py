"""Status endpoint for local CLI providers (never runs a model)."""

from typing import Literal

from fastapi import APIRouter

from api.v1.dependencies import CurrentUser
from providers.cli import cli_status
from providers.cli.status import cli_models
from schemas import CLIStatusResponse, CLIToolStatusResponse

router = APIRouter(prefix="/providers/cli", tags=["cli"])


@router.get("/status", response_model=CLIStatusResponse, summary="CLI provider status")
async def get_cli_status() -> CLIStatusResponse:
    status = await cli_status()
    return CLIStatusResponse(
        enabled=status.enabled,
        in_container=status.in_container,
        tools={
            name: CLIToolStatusResponse(
                installed=tool.installed,
                logged_in=tool.logged_in,
                detail=tool.detail,
            )
            for name, tool in status.tools.items()
        },
    )


@router.get("/models/{provider}")
async def get_cli_models(
    provider: Literal["cli-codex", "cli-opencode"], current_user: CurrentUser
) -> list[str]:
    return await cli_models(provider)
