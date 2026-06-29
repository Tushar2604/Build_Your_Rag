"""Structured logging + Prometheus metrics setup.

JSON logs in production (machine-parseable for any log aggregator's free tier),
pretty console logs in development. A correlation id is bound per request by the
API middleware so a single request can be traced across logs.
"""

from __future__ import annotations

import logging

import structlog
from prometheus_client import Counter, Histogram

from src.config import Settings

# --- Metrics (scraped at /metrics) ---
REQUEST_COUNT = Counter(
    "http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens used", ["provider"])
INGEST_DOCS = Counter("ingest_documents_total", "Documents ingested", ["status"])


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        format="%(message)s", level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if settings.is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
