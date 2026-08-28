"""One HTTP connection pool for the whole process.

Every outbound integration used to open its own `httpx.AsyncClient` per call:

    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(...)

That is correct but does not scale. Each `AsyncClient` is a *connection pool*,
so building one per call means a fresh TCP connect and TLS handshake on every
embedding, every WhatsApp reply, every broadcast send — the handshake often
costing more than the request itself. Under concurrent traffic it also leaks
ephemeral ports (sockets sit in TIME_WAIT far longer than the request that
opened them), which is how a box that looks idle starts refusing connections.

Sharing one client per host group fixes both: connections are kept alive and
reused across requests, and HTTP/2 multiplexes concurrent calls to the same
host onto a single connection.

Clients are keyed by name so a slow dependency cannot starve a fast one — the
pool limits below are *per key*, so a stalled voice-clone upload can never
consume the connection budget the chatbot's embeddings need.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

log = structlog.get_logger(__name__)

# Sized for a single web process serving many tenants at once. `max_connections`
# is the hard ceiling per client; `max_keepalive_connections` is how many stay
# warm between bursts. Keepalive expiry is deliberately longer than the gap
# between messages in a busy campaign, so a run of replies reuses one connection
# instead of renegotiating TLS for each.
_DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

_clients: dict[str, httpx.AsyncClient] = {}
_lock = asyncio.Lock()


async def get_client(
    name: str = "default",
    *,
    timeout: float = 30.0,
    base_url: str = "",
    headers: dict[str, str] | None = None,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncClient:
    """Return the shared client for `name`, creating it on first use.

    The double-checked lock matters: `httpx.AsyncClient()` is synchronous to
    construct, but the `await` on the lock is a scheduling point, so two
    coroutines racing on a cold cache could otherwise each build a client and
    one would be silently dropped — leaking its pool.
    """
    client = _clients.get(name)
    if client is not None and not client.is_closed:
        return client

    async with _lock:
        client = _clients.get(name)
        if client is not None and not client.is_closed:
            return client
        client = httpx.AsyncClient(
            timeout=timeout,
            base_url=base_url,
            headers=headers or {},
            limits=limits or _DEFAULT_LIMITS,
            # HTTP/1.1 with keepalive. HTTP/2 would multiplex concurrent calls
            # to one host onto a single connection, but it needs the optional
            # `h2` package; without it httpx raises at construction. Keepalive
            # reuse is the bulk of the win here anyway.
            http2=False,
        )
        _clients[name] = client
        log.debug("http.pool_opened", name=name)
        return client


async def close_clients() -> None:
    """Close every pooled client. Called once from the app's lifespan shutdown.

    Best-effort per client: one that fails to close must not prevent the rest
    from being released, or a redeploy leaks sockets on the way out.
    """
    async with _lock:
        for name, client in list(_clients.items()):
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - shutdown is best-effort
                log.warning("http.pool_close_failed", name=name)
        _clients.clear()
        log.debug("http.pools_closed")
