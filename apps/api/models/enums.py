"""Domain enums stored as constrained VARCHAR columns (no native PG enums)."""

from enum import StrEnum
from typing import Any

from sqlalchemy import String, TypeDecorator


class StrEnumType(TypeDecorator):
    """Persist a ``StrEnum`` as VARCHAR while giving it back as an enum."""

    impl = String
    cache_ok = True

    def __init__(self, enum_type: type[StrEnum], length: int = 20) -> None:
        super().__init__(length=length)
        self.enum_type = enum_type

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> StrEnum | None:
        return None if value is None else self.enum_type(value)


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
