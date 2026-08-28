"""Error classification, circuit breaking, and bulkheads for the LLM chain.

The failover chain (OpenAI -> Groq -> Gemini) already existed, but it behaved
badly under concurrent traffic for three reasons, all of which this module
addresses:

1. **Rate limits were retried instead of routed around.** Each provider's
   `generate` was wrapped in `@retry(stop_after_attempt(3),
   wait_exponential(...))`, which retries *the same provider* on any exception
   — including HTTP 429. So a rate-limited request slept ~3-10s on OpenAI
   before it ever tried Groq, and the retries themselves added load to the
   provider that was already asking us to slow down. A 429 is not a transient
   glitch to wait out; it is the provider telling us to go somewhere else, and
   with three keys configured there *is* somewhere else.

2. **No memory between requests.** When a provider was down or throttling,
   every single request still paid the full retry cost on it before failing
   over. At 100 concurrent chats that is 100 independent retry storms against
   a backend already known to be failing. The circuit breaker gives the chain
   a short memory: once a provider trips, it is skipped outright until a
   cooldown elapses, then probed with a single request.

3. **Unbounded concurrency.** Nothing capped how many calls were in flight to
   one provider, so a traffic burst would self-inflict the rate limit the
   failover was there to survive. The bulkhead caps in-flight calls per
   provider, which keeps each account inside its quota and applies
   backpressure instead of amplifying the spike.
"""

from __future__ import annotations

import asyncio
import time

import structlog

log = structlog.get_logger(__name__)


# --- Error classification -------------------------------------------------

# Matched against the exception's class name and message, because each SDK
# raises its own type (openai.RateLimitError, groq.RateLimitError,
# google.genai.errors.ClientError, httpx.HTTPStatusError) and importing all of
# them here would couple this module to every optional dependency.
_RATE_LIMIT_MARKERS = (
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
    "resource_exhausted",
    "resource exhausted",
    "429",
)

_OVERLOADED_MARKERS = (
    "overloaded",
    "capacity",
    "service unavailable",
    "serviceunavailable",
    "unavailable",
    "503",
    "502",
    "504",
    "timeout",
    "timed out",
)


def _text_of(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return f"{type(exc).__name__} {exc} {status or ''}".lower()


def is_rate_limited(exc: BaseException) -> bool:
    """Is this the provider telling us to back off?

    Rate limits are the one failure that must NOT be retried on the same
    backend — retrying is what turns a throttle into an outage.
    """
    return any(m in _text_of(exc) for m in _RATE_LIMIT_MARKERS)


def is_transient(exc: BaseException) -> bool:
    """A blip worth one quick retry on the same provider (a dropped
    connection, a 503) rather than an immediate failover."""
    return any(m in _text_of(exc) for m in _OVERLOADED_MARKERS)


def should_trip_circuit(exc: BaseException) -> bool:
    """Does this failure say something about the *provider* rather than the
    request? A rate limit or an outage does; a malformed prompt does not, and
    tripping on it would take a healthy backend out of rotation."""
    return is_rate_limited(exc) or is_transient(exc)


# --- Circuit breaker ------------------------------------------------------


class CircuitBreaker:
    """Per-provider health gate: closed (allow), open (skip), half-open (probe).

    Deliberately tiny and in-process. A shared/distributed breaker would need
    Redis and would couple every web process together; the win here comes
    almost entirely from not hammering a known-dead backend on *this* process's
    own concurrent requests, which a local breaker delivers.
    """

    def __init__(self, *, threshold: int = 5, cooldown_seconds: float = 30.0) -> None:
        self._threshold = max(1, threshold)
        # Not clamped to a minimum: a caller that asks for a short cooldown
        # (a test, or an operator on a provider with a fast-recovering quota)
        # must actually get one, or the setting silently lies.
        self._cooldown = max(0.0, cooldown_seconds)
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """True while the provider should be skipped entirely."""
        if self._opened_at is None:
            return False
        if (time.monotonic() - self._opened_at) >= self._cooldown:
            # Cooldown elapsed: let exactly one request through to probe. The
            # breaker stays "half-open" until that probe reports back — a
            # success closes it, a failure re-opens it for another cooldown.
            self._opened_at = None
            self._failures = self._threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self, provider: str) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            log.warning(
                "llm.circuit_open",
                provider=provider,
                failures=self._failures,
                cooldown_seconds=self._cooldown,
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "open": self._opened_at is not None,
            "failures": self._failures,
            "seconds_until_retry": (
                None
                if self._opened_at is None
                else max(0.0, self._cooldown - (time.monotonic() - self._opened_at))
            ),
        }


# --- Bulkhead -------------------------------------------------------------


class Bulkhead:
    """Caps in-flight calls to one provider.

    The semaphore is created lazily because a `Container` is built at import
    time in some paths, and binding an `asyncio.Semaphore` to a loop that is
    not the one serving requests raises at acquire time.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._sem: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem = asyncio.Semaphore(self._limit)
            self._loop = loop
        return self._sem

    def __call__(self):  # type: ignore[no-untyped-def]
        return self._semaphore()
