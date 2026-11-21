"""CLI provider status response."""

from pydantic import BaseModel


class CLIToolStatusResponse(BaseModel):
    installed: bool
    logged_in: bool
    detail: str


class CLIStatusResponse(BaseModel):
    enabled: bool
    in_container: bool
    tools: dict[str, CLIToolStatusResponse]
