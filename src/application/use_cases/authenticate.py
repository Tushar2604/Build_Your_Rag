"""Authenticate a user and issue a JWT pair."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr

from src.application.dtos import AuthOutput
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import PasswordHasher, TokenService
from src.domain.shared.errors import PermissionDeniedError


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class AuthenticateUser:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens

    async def execute(self, data: LoginInput) -> AuthOutput:
        async with self._uow as uow:
            user = await uow.users.get_by_email(data.email)
            if user is None or not user.is_active:
                raise PermissionDeniedError("Invalid credentials.")
            if not self._hasher.verify(data.password, user.password_hash):
                raise PermissionDeniedError("Invalid credentials.")

        pair = self._tokens.issue(
            user_id=str(user.id), tenant_id=str(user.tenant_id), role=user.role.value
        )
        return AuthOutput(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
