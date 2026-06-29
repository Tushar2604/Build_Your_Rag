"""Password and API-key hashing (Argon2id)."""

from __future__ import annotations

import hashlib

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import VerifyMismatchError


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._ph = _Argon2()

    def hash(self, plain: str) -> str:
        return self._ph.hash(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        try:
            return self._ph.verify(hashed, plain)
        except VerifyMismatchError:
            return False


def hash_api_key(raw_key: str) -> str:
    """API keys are high-entropy, so a fast SHA-256 is appropriate (and lets us
    look them up by hash without a per-row Argon2 verify)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
