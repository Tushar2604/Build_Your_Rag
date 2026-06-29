"""Unit tests for the public-widget guards (no DB required)."""

from __future__ import annotations

from src.domain.chatbot.entities import (
    PUBLIC_KEY_PREFIX,
    WidgetConfig,
    generate_public_key,
    origin_allowed,
)
from src.infrastructure.ratelimit.anon import SlidingWindowRateLimiter


# --- publishable key ---------------------------------------------------------
def test_public_key_has_prefix_and_is_unique() -> None:
    a = generate_public_key()
    b = generate_public_key()
    assert a.startswith(PUBLIC_KEY_PREFIX)
    assert a != b
    assert len(a) > len(PUBLIC_KEY_PREFIX) + 10


# --- origin allowlist --------------------------------------------------------
def test_empty_allowlist_is_open() -> None:
    assert origin_allowed("https://anything.com", []) is True
    assert origin_allowed(None, []) is True


def test_exact_origin_match() -> None:
    allowed = ["https://example.com"]
    assert origin_allowed("https://example.com", allowed) is True
    assert origin_allowed("https://example.com/", allowed) is True  # trailing slash tolerated
    assert origin_allowed("https://evil.com", allowed) is False


def test_missing_origin_rejected_when_allowlist_set() -> None:
    assert origin_allowed(None, ["https://example.com"]) is False


def test_wildcard_subdomain_match() -> None:
    allowed = ["*.example.com"]
    assert origin_allowed("https://app.example.com", allowed) is True
    assert origin_allowed("https://deep.app.example.com", allowed) is True
    # the apex itself is not a subdomain, so it does not match the wildcard
    assert origin_allowed("https://example.com", allowed) is False
    assert origin_allowed("https://notexample.com", allowed) is False


def test_case_insensitive_origin() -> None:
    assert origin_allowed("https://Example.com", ["https://example.com"]) is True


# --- rate limiter ------------------------------------------------------------
def test_rate_limiter_blocks_after_cap() -> None:
    rl = SlidingWindowRateLimiter(max_events=3, window_seconds=60)
    assert [rl.allow("k", now=t) for t in (1, 2, 3)] == [True, True, True]
    assert rl.allow("k", now=4) is False  # 4th within window blocked


def test_rate_limiter_window_slides() -> None:
    rl = SlidingWindowRateLimiter(max_events=2, window_seconds=10)
    assert rl.allow("k", now=0) is True
    assert rl.allow("k", now=1) is True
    assert rl.allow("k", now=2) is False
    # first two age out by t=12; capacity returns
    assert rl.allow("k", now=12) is True


def test_rate_limiter_keys_are_independent() -> None:
    rl = SlidingWindowRateLimiter(max_events=1, window_seconds=60)
    assert rl.allow("a", now=0) is True
    assert rl.allow("b", now=0) is True
    assert rl.allow("a", now=1) is False


def test_blocked_event_does_not_extend_window() -> None:
    rl = SlidingWindowRateLimiter(max_events=1, window_seconds=10)
    assert rl.allow("k", now=0) is True
    assert rl.allow("k", now=5) is False  # blocked, not recorded
    # the only recorded hit (t=0) ages out at t=10, so t=11 is allowed
    assert rl.allow("k", now=11) is True


# --- widget config normalization --------------------------------------------
def test_widget_config_normalizes_bad_position() -> None:
    wc = WidgetConfig(launcher_position="top-left").normalized()
    assert wc.launcher_position == "bottom-right"


def test_widget_config_keeps_valid_position() -> None:
    wc = WidgetConfig(launcher_position="bottom-left").normalized()
    assert wc.launcher_position == "bottom-left"
