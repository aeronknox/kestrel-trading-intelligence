import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel


def _validate_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain letters and numbers")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    _pw = field_validator("password")(_validate_password)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class ResetPasswordRequest(TokenRequest):
    new_password: str = Field(max_length=128)

    _pw = field_validator("new_password")(_validate_password)


class DeleteAccountRequest(BaseModel):
    password: str | None = Field(None, max_length=128, description="Required except for demo sandboxes")
    confirm: str = Field(description='Type "DELETE" to confirm')


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(max_length=128)

    _pw = field_validator("new_password")(_validate_password)


class UserSettingsOut(ORMModel):
    default_timeframe: str
    default_symbol: str
    risk_tolerance: str
    preferences: dict


class UserSettingsUpdate(BaseModel):
    default_timeframe: Literal["1m", "5m", "15m", "1h", "6h", "1d"] | None = None
    default_symbol: str | None = Field(None, max_length=32)
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] | None = None
    preferences: dict | None = None


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    email_verified: bool = False
    is_demo: bool = False
    created_at: datetime
    last_login_at: datetime | None
    settings: UserSettingsOut | None = None


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class AuditLogOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: str | None
    ip_address: str | None
    details: dict
    created_at: datetime
