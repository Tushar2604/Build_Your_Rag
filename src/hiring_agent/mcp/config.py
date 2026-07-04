"""Hiring Agent MCP — server discovery configuration.

Reads `HIRING_MCP_SERVERS` from the environment: a JSON array of server
descriptors. If unset, defaults to the bundled Hiring MCP server (stdio).

Example env value:
    HIRING_MCP_SERVERS='[
      {"name":"hiring","transport":"stdio",
       "command":["python","-m","src.hiring_agent.mcp.server"],
       "timeout_seconds":30,"max_retries":3},
      {"name":"rag","transport":"stdio",
       "command":["python","-m","src.interfaces.mcp.server"],
       "env":{"MCP_TENANT_API_KEY":"sk_xxx"},"timeout_seconds":30,"max_retries":2}
    ]'
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_ENV_KEY = "HIRING_MCP_SERVERS"

_DEFAULT_SERVERS: list[dict] = [
    {
        "name": "hiring",
        "transport": "stdio",
        "command": ["python", "-m", "src.hiring_agent.mcp.server"],
        "env": {},
        "timeout_seconds": 30.0,
        "max_retries": 3,
    }
]


@dataclass(frozen=True)
class MCPServerConfig:
    """Describes how to reach and authenticate with one MCP server."""

    name: str
    transport: str  # "stdio" | "sse"
    # stdio transport
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # sse transport
    url: str = ""
    # resilience
    timeout_seconds: float = 30.0
    max_retries: int = 3


def load_hiring_mcp_servers() -> list[MCPServerConfig]:
    """Return server configs from env, falling back to the bundled default."""
    raw = os.environ.get(_ENV_KEY)
    descriptors: list[dict] = json.loads(raw) if raw else _DEFAULT_SERVERS

    configs: list[MCPServerConfig] = []
    for d in descriptors:
        # Allow partial dicts — unrecognised keys are silently dropped.
        known = {f.name for f in MCPServerConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        configs.append(MCPServerConfig(**{k: v for k, v in d.items() if k in known}))
    return configs
