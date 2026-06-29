"""Tests for configuration guards (production-secret enforcement, DSN driver)."""

from __future__ import annotations

import pytest
from src.config.settings import Settings


def test_dev_allows_placeholder_secret() -> None:
    s = Settings(app_env="development", jwt_secret="change-me")
    assert s.jwt_secret == "change-me"


@pytest.mark.parametrize("secret", ["", "change-me", "change-me-please-use-a-long-random-string"])
def test_production_rejects_insecure_secret(secret: str) -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret=secret)


def test_production_accepts_strong_secret() -> None:
    s = Settings(app_env="production", jwt_secret="s3cr3t-very-long-random-value-xyz")
    assert s.is_production is True


def test_database_url_gets_async_driver() -> None:
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_use_object_storage_toggle() -> None:
    assert Settings(r2_endpoint_url="", r2_access_key_id="").use_object_storage is False
    assert (
        Settings(r2_endpoint_url="https://x.r2", r2_access_key_id="k").use_object_storage
        is True
    )
