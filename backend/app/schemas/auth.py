"""Auth request and response shapes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    """A user as the API returns it. Note the absence of password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    role: UserRole
