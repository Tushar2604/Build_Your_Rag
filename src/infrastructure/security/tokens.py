"""JWT issuance and verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from src.application.ports.services import TokenPair
from src.config import Settings


class JwtTokenService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._alg = settings.jwt_algorithm
        self._access_ttl = timedelta(minutes=settings.jwt_access_ttl_minutes)
        self._refresh_ttl = timedelta(days=settings.jwt_refresh_ttl_days)

    def issue(self, *, user_id: str, tenant_id: str, role: str) -> TokenPair:
        now = datetime.now(UTC)
        base = {"sub": user_id, "tenant_id": tenant_id, "role": role, "iat": now}
        access = jwt.encode(
            {**base, "type": "access", "exp": now + self._access_ttl},
            self._secret,
            algorithm=self._alg,
        )
        refresh = jwt.encode(
            {**base, "type": "refresh", "exp": now + self._refresh_ttl},
            self._secret,
            algorithm=self._alg,
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    def decode(self, token: str) -> dict:
        return jwt.decode(token, self._secret, algorithms=[self._alg])
