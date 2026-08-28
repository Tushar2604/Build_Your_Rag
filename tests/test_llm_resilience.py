"""Guards for the behaviour that lets one process serve many chatbots at once.

The failover chain (OpenAI -> Groq -> Gemini) existed already, but three things
made it fail under exactly the load it was meant to survive — simultaneous
requests from many linked WhatsApp accounts:

  1. every provider retried *itself* three times with exponential backoff on any
     error, including HTTP 429, so a throttled request slept for seconds on the
     one backend that had just said "slow down" before trying a healthy one;
  2. nothing remembered that a provider was failing, so all N concurrent
     requests independently repeated that retry storm;
  3. nothing capped in-flight calls, so a burst self-inflicted the rate limit
     the chain was there to route around.

These tests pin the fixed behaviour rather than the implementation: what a
caller observes is "a rate limit costs one hop, not a stall".
"""

from __future__ import annotations

import asyncio

import pytest
from src.application.ports.services import LLMResult
from src.infrastructure.llm.providers import FailoverLLM
from src.infrastructure.llm.resilience import (
    Bulkhead,
    CircuitBreaker,
    is_rate_limited,
    is_transient,
    should_trip_circuit,
)


class RateLimited(Exception):
    """Shaped like a real SDK's 429 (openai.RateLimitError, groq.RateLimitError)."""

    def __init__(self) -> None:
        super().__init__("Rate limit reached for requests")
        self.status_code = 429


class Down(Exception):
    def __init__(self) -> None:
        super().__init__("Service Unavailable")
        self.status_code = 503


class BadPrompt(Exception):
    """A request-level failure — says nothing about provider health."""


class FakeProvider:
    """Records calls so a test can assert how often a backend was reached."""

    def __init__(self, name: str, *, fails_with: type[Exception] | None = None) -> None:
        self.name = name
        self._fails_with = fails_with
        self.calls = 0
        self.concurrent = 0
        self.peak_concurrent = 0

    async def generate(self, system: str, user: str) -> LLMResult:
        self.calls += 1
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        try:
            await asyncio.sleep(0)  # a scheduling point, so overlap is possible
            if self._fails_with is not None:
                raise self._fails_with()
            return LLMResult(
                text=f"answer from {self.name}",
                tokens_used=1,
                provider=self.name,
                model=f"{self.name}-model",
            )
        finally:
            self.concurrent -= 1


# --- Error classification -------------------------------------------------


def test_a_rate_limit_is_recognised_across_sdk_shapes() -> None:
    assert is_rate_limited(RateLimited())
    assert is_rate_limited(Exception("429 Too Many Requests"))
    assert is_rate_limited(Exception("RESOURCE_EXHAUSTED"))
    assert is_rate_limited(Exception("You exceeded your current quota"))


def test_an_outage_is_transient_but_not_a_rate_limit() -> None:
    assert is_transient(Down())
    assert not is_rate_limited(Down())


def test_a_request_level_error_never_trips_the_breaker() -> None:
    # Tripping on a bad prompt would pull a perfectly healthy account out of
    # rotation for every other tenant on the process.
    assert not should_trip_circuit(BadPrompt("prompt too long"))
    assert should_trip_circuit(RateLimited())
    assert should_trip_circuit(Down())


# --- Failover routing -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_rate_limited_provider_is_skipped_after_a_single_attempt() -> None:
    """The core regression: a 429 must cost one hop, not a retry storm."""
    primary = FakeProvider("openai", fails_with=RateLimited)
    secondary = FakeProvider("groq")
    llm = FailoverLLM([primary, secondary])

    result = await llm.generate("sys", "hello")

    assert result.provider == "groq"
    assert primary.calls == 1, "a rate limit must not be retried on the same provider"


@pytest.mark.asyncio
async def test_the_chain_falls_through_to_the_last_healthy_provider() -> None:
    a = FakeProvider("openai", fails_with=RateLimited)
    b = FakeProvider("groq", fails_with=Down)
    c = FakeProvider("gemini")
    llm = FailoverLLM([a, b, c])

    assert (await llm.generate("sys", "hi")).provider == "gemini"


@pytest.mark.asyncio
async def test_every_provider_failing_raises_rather_than_answering_falsely() -> None:
    llm = FailoverLLM(
        [FakeProvider("openai", fails_with=Down), FakeProvider("groq", fails_with=Down)]
    )
    with pytest.raises(Down):
        await llm.generate("sys", "hi")


# --- Circuit breaker ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_provider_stops_being_tried_first() -> None:
    """The load-shedding property: once a backend is known bad, concurrent
    traffic must stop paying its failure cost on every request."""
    primary = FakeProvider("openai", fails_with=RateLimited)
    secondary = FakeProvider("groq")
    llm = FailoverLLM([primary, secondary], breaker_threshold=3)

    for _ in range(3):
        await llm.generate("sys", "hi")
    assert primary.calls == 3

    calls_before = primary.calls
    for _ in range(10):
        assert (await llm.generate("sys", "hi")).provider == "groq"

    assert primary.calls == calls_before, (
        "a tripped provider must be skipped, not re-probed by every request"
    )


@pytest.mark.asyncio
async def test_a_tripped_provider_is_probed_again_after_its_cooldown() -> None:
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=0.05)
    breaker.record_failure("openai")
    breaker.record_failure("openai")
    assert breaker.is_open

    await asyncio.sleep(0.06)
    assert not breaker.is_open, "cooldown must let one probe through"


def test_a_success_closes_the_breaker() -> None:
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=60)
    breaker.record_failure("openai")
    breaker.record_success()
    breaker.record_failure("openai")
    assert not breaker.is_open, "the failure count must reset on a good response"


@pytest.mark.asyncio
async def test_an_all_tripped_chain_still_tries_rather_than_hard_failing() -> None:
    """Degrade to slow, never to broken: stale in-process bookkeeping must not
    be able to turn a recovered provider into an outage."""
    only = FakeProvider("openai")
    llm = FailoverLLM([only], breaker_threshold=1)
    llm._breakers["openai"].record_failure("openai")  # force it open

    assert (await llm.generate("sys", "hi")).provider == "openai"


# --- Bulkhead -------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_calls_to_one_provider_are_capped() -> None:
    """What keeps a burst inside the account's quota instead of provoking the
    429s the failover exists to survive."""
    provider = FakeProvider("openai")
    llm = FailoverLLM([provider], max_concurrency_per_provider=3)

    await asyncio.gather(*(llm.generate("sys", f"q{i}") for i in range(25)))

    assert provider.calls == 25, "every request is served, just paced"
    assert provider.peak_concurrent <= 3, (
        f"bulkhead breached: {provider.peak_concurrent} calls were in flight at once"
    )


@pytest.mark.asyncio
async def test_simultaneous_requests_spread_across_the_configured_accounts() -> None:
    """The headline behaviour: many chatbots asking at once still all get
    answered, with the throttled account contributing nothing after it trips."""
    primary = FakeProvider("openai", fails_with=RateLimited)
    secondary = FakeProvider("groq")
    llm = FailoverLLM([primary, secondary], breaker_threshold=2)

    results = await asyncio.gather(
        *(llm.generate("sys", f"q{i}") for i in range(40))
    )

    assert len(results) == 40
    assert all(r.provider == "groq" for r in results)
    assert primary.calls < 40, "the throttled account must stop absorbing traffic"


def test_a_bulkhead_rebinds_when_the_event_loop_changes() -> None:
    """Containers are process-wide singletons but tests (and Uvicorn's reloader)
    run more than one loop; a semaphore bound to a dead loop raises on acquire."""
    bulkhead = Bulkhead(2)

    async def use_it() -> None:
        async with bulkhead():
            await asyncio.sleep(0)

    asyncio.run(use_it())
    asyncio.run(use_it())  # a different loop — must not raise
