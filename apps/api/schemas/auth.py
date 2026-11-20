"""Authentication request/response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.fields import EmailAddress, OptionalFullName, StrongPassword


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailAddress
    password: StrongPassword
    full_name: OptionalFullName = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailAddress
    # Strength is enforced at registration/change time only; login accepts the
    # exact password that was originally stored, whatever the current policy.
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    new_password: StrongPassword


class TokenPair(BaseModel):
    """Internal service result: the refresh token is only used to set a cookie."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int


class TokenResponse(BaseModel):
    """Public token response. The refresh token never reaches the response body."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int
