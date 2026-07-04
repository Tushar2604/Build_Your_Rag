"""Hiring Agent MCP client — dynamic server discovery and tool dispatch.

`MCPClientManager` is the single point through which every Hiring Agent
tool reaches an MCP server:

1. On first use it connects to each configured server and calls
   `list_tools()` to build a `{tool_name → server_config}` routing table
   (dynamic discovery).
2. `call_tool()` routes the call to the correct server, enforcing a
   per-call timeout and a retry policy (connection errors only).
3. Errors are converted to the structured error hierarchy in `errors.py`.
4. Every significant event is logged with structlog.

The `mcp` SDK is imported inside methods (deferred) so the module is
importable — and the app starts — even when the optional `mcp` dependency
is not installed.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.hiring_agent.mcp.config import MCPServerConfig, load_hiring_mcp_servers
from src.hiring_agent.mcp.errors import (
    MCPConnectionError,
    MCPNotInstalledError,
    MCPRetryExhausted,
    MCPServerNotFoundError,
    MCPTimeoutError,
    MCPToolError,
)

log = structlog.get_logger(__name__)


class MCPClientManager:
    """Manages connections to one or more MCP servers on behalf of the Hiring Agent.

    Thread-safety note: safe for concurrent asyncio use. The discovery lock
    ensures `_discover_impl` runs exactly once even under concurrent callers.
    """

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = configs
        # tool_name → server config that exposes it
        self._routing: dict[str, MCPServerConfig] = {}
        self._discovered = False
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover_servers(self) -> dict[str, list[str]]:
        """Connect to every configured server, list its tools, and return
        the catalog as {server_name: [tool_name, …]}.

        Useful for health-check / debug endpoints.
        """
        await self._ensure_discovered()
        catalog: dict[str, list[str]] = {}
        for tool_name, cfg in self._routing.items():
            catalog.setdefault(cfg.name, []).append(tool_name)
        return catalog

    async def list_all_tools(self) -> list[dict[str, str]]:
        """Return [{name, server, description}] for every discovered tool."""
        await self._ensure_discovered()
        return [
            {"name": name, "server": cfg.name}
            for name, cfg in self._routing.items()
        ]

    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Invoke `tool_name` on its registered MCP server.

        Raises:
            MCPServerNotFoundError  — no server has this tool
            MCPNotInstalledError    — `mcp` package is missing
            MCPTimeoutError         — call exceeded the timeout
            MCPToolError            — server returned an error payload
            MCPRetryExhausted       — all connection-retry attempts failed
        """
        await self._ensure_discovered()

        cfg = self._routing.get(tool_name)
        if cfg is None:
            raise MCPServerNotFoundError(tool_name)

        effective_timeout = timeout if timeout is not None else cfg.timeout_seconds
        return await self._call_with_retry(cfg, tool_name, params, effective_timeout)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _ensure_discovered(self) -> None:
        if self._discovered:
            return
        async with self._lock:
            if self._discovered:  # double-checked locking
                return
            await self._discover_impl()

    async def _discover_impl(self) -> None:
        log.info("mcp.discovery.start", server_count=len(self._configs))
        for cfg in self._configs:
            try:
                tool_names = await self._list_tools_from_server(cfg)
                registered = 0
                for name in tool_names:
                    if name in self._routing:
                        log.warning(
                            "mcp.discovery.duplicate_tool",
                            tool=name,
                            existing_server=self._routing[name].name,
                            skipped_server=cfg.name,
                        )
                    else:
                        self._routing[name] = cfg
                        registered += 1
                log.info(
                    "mcp.discovery.server_ok",
                    server=cfg.name,
                    tools_registered=registered,
                )
            except MCPNotInstalledError:
                log.warning(
                    "mcp.discovery.mcp_not_installed",
                    server=cfg.name,
                    hint="pip install 'rag-platform[mcp]'",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "mcp.discovery.server_failed",
                    server=cfg.name,
                    error=str(exc),
                )
        self._discovered = True
        log.info("mcp.discovery.complete", total_tools=len(self._routing))

    async def _list_tools_from_server(self, cfg: MCPServerConfig) -> list[str]:
        """Open a short-lived connection, list tools, then close."""
        if cfg.transport == "stdio":
            return await self._list_tools_stdio(cfg)
        if cfg.transport == "sse":
            return await self._list_tools_sse(cfg)
        raise MCPConnectionError(f"Unknown transport '{cfg.transport}' for server '{cfg.name}'")

    async def _list_tools_stdio(self, cfg: MCPServerConfig) -> list[str]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise MCPNotInstalledError(
                "mcp package not installed. Run: pip install 'rag-platform[mcp]'"
            ) from exc

        params = StdioServerParameters(
            command=cfg.command[0],
            args=cfg.command[1:],
            env={**os.environ, **cfg.env} if cfg.env else None,
        )
        # Use a longer timeout for discovery — subprocess startup can be slow.
        discovery_timeout = max(cfg.timeout_seconds, 60.0)
        try:
            async with asyncio.timeout(discovery_timeout):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [t.name for t in result.tools]
        except asyncio.TimeoutError as exc:
            raise MCPConnectionError(
                f"Timed out discovering tools from '{cfg.name}' after {discovery_timeout}s"
            ) from exc
        except Exception as exc:
            raise MCPConnectionError(
                f"Failed to list tools from '{cfg.name}': {exc}"
            ) from exc

    async def _list_tools_sse(self, cfg: MCPServerConfig) -> list[str]:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:
            raise MCPNotInstalledError(
                "mcp package not installed. Run: pip install 'rag-platform[mcp]'"
            ) from exc

        try:
            async with asyncio.timeout(cfg.timeout_seconds):
                async with sse_client(cfg.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [t.name for t in result.tools]
        except asyncio.TimeoutError as exc:
            raise MCPConnectionError(
                f"Timed out discovering tools from '{cfg.name}'"
            ) from exc
        except Exception as exc:
            raise MCPConnectionError(f"Failed to list tools from '{cfg.name}': {exc}") from exc

    # ------------------------------------------------------------------
    # Call dispatch — retry + timeout
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        cfg: MCPServerConfig,
        tool_name: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Invoke the tool with exponential-backoff retry on connection errors."""
        attempt_number = 0

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(cfg.max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                retry=retry_if_exception_type(MCPConnectionError),
                reraise=True,
            ):
                with attempt:
                    attempt_number += 1
                    log.info(
                        "mcp.call_tool",
                        tool=tool_name,
                        server=cfg.name,
                        attempt=attempt_number,
                        timeout=timeout,
                    )
                    result = await self._call_tool_on_server(cfg, tool_name, params, timeout)
                    log.info(
                        "mcp.call_tool.ok",
                        tool=tool_name,
                        server=cfg.name,
                        attempt=attempt_number,
                    )
                    return result
        except MCPConnectionError as exc:
            log.error(
                "mcp.call_tool.retry_exhausted",
                tool=tool_name,
                server=cfg.name,
                attempts=attempt_number,
                error=str(exc),
            )
            raise MCPRetryExhausted(tool_name, attempt_number, exc) from exc

        raise RuntimeError("unreachable")  # satisfies type checker

    async def _call_tool_on_server(
        self,
        cfg: MCPServerConfig,
        tool_name: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        if cfg.transport == "stdio":
            return await self._call_tool_stdio(cfg, tool_name, params, timeout)
        if cfg.transport == "sse":
            return await self._call_tool_sse(cfg, tool_name, params, timeout)
        raise MCPConnectionError(f"Unsupported transport '{cfg.transport}'")

    async def _call_tool_stdio(
        self,
        cfg: MCPServerConfig,
        tool_name: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise MCPNotInstalledError(
                "mcp package not installed. Run: pip install 'rag-platform[mcp]'"
            ) from exc

        server_params = StdioServerParameters(
            command=cfg.command[0],
            args=cfg.command[1:],
            env={**os.environ, **cfg.env} if cfg.env else None,
        )
        try:
            async with asyncio.timeout(timeout):
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        call_result = await session.call_tool(tool_name, params)
        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(tool_name, timeout) from exc
        except (MCPTimeoutError, MCPToolError):
            raise
        except Exception as exc:
            raise MCPConnectionError(
                f"stdio connection to '{cfg.name}' failed: {exc}"
            ) from exc

        return self._parse_call_result(call_result, tool_name)

    async def _call_tool_sse(
        self,
        cfg: MCPServerConfig,
        tool_name: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as exc:
            raise MCPNotInstalledError(
                "mcp package not installed. Run: pip install 'rag-platform[mcp]'"
            ) from exc

        try:
            async with asyncio.timeout(timeout):
                async with sse_client(cfg.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        call_result = await session.call_tool(tool_name, params)
        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(tool_name, timeout) from exc
        except (MCPTimeoutError, MCPToolError):
            raise
        except Exception as exc:
            raise MCPConnectionError(
                f"SSE connection to '{cfg.url}' failed: {exc}"
            ) from exc

        return self._parse_call_result(call_result, tool_name)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_call_result(call_result: Any, tool_name: str) -> dict[str, Any]:
        """Convert an MCP CallToolResult to a plain dict.

        FastMCP serialises dict return values as JSON in a TextContent block.
        We parse that back to a dict. If the content is not valid JSON we
        wrap it under the "observation" key so callers always get a dict.
        """
        if getattr(call_result, "isError", False):
            content = call_result.content or []
            text = getattr(content[0], "text", str(content)) if content else "tool error"
            raise MCPToolError(tool_name, text)

        content = getattr(call_result, "content", []) or []
        if not content:
            return {"observation": f"Tool '{tool_name}' returned no content."}

        text = getattr(content[0], "text", None)
        if text is None:
            return {"observation": str(content[0])}

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return {"observation": str(data), "raw": data}
        except json.JSONDecodeError:
            return {"observation": text, "raw": text}
