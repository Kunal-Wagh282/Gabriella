import uuid

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import ApiModel


class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class LoginRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PreferencesOut(ApiModel):
    preferred_store_id: int | None
    personalization_enabled: bool


class PreferencesUpdate(ApiModel):
    preferred_store_id: int | None = None
    personalization_enabled: bool | None = None


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    preferences: PreferencesOut
