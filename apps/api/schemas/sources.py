"""External source import requests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["url", "github"]
    url: str | None = Field(default=None, max_length=2048)
    owner: str | None = Field(default=None, max_length=200)
    repo: str | None = Field(default=None, max_length=200)
    ref: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=500)
    max_depth: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def validate_target(self):
        if self.type == "url" and not self.url:
            raise ValueError("url is required for a URL source")
        if self.type == "github" and not (self.owner and self.repo):
            raise ValueError("owner and repo are required for a GitHub source")
        return self
