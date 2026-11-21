"""Status endpoint for local CLI providers (never runs a model)."""

from fastapi import APIRouter

from providers.cli import cli_status
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
