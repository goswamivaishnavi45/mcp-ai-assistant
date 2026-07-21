"""
Connects to one or more MCP servers over stdio, keeps the connections
alive for the life of the app, and exposes a single flat, namespaced
tool registry + a dispatch method. This is the "single unified
interface" layer: Gemini never talks to individual MCP servers, it
only ever sees this manager.
"""
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVERS_DIR = Path(__file__).resolve().parent / "servers"

SERVER_CONFIGS = {
    "filesystem": SERVERS_DIR / "filesystem_server.py",
    "websearch": SERVERS_DIR / "websearch_server.py",
}


@dataclass
class ToolInfo:
    server: str
    name: str
    raw_name: str
    description: str
    input_schema: dict


class MCPManager:
    def __init__(self):
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, ToolInfo] = {}

    async def connect_all(self):
        for server_name, script_path in SERVER_CONFIGS.items():
            print(f"Connecting to {server_name}...", file=sys.stderr)

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            params = StdioServerParameters(
                command=sys.executable,
                args=["-u", str(script_path)],
                env=env,
            )


            read, write = await self._stack.enter_async_context(stdio_client(params))
            print(f"{server_name}: stdio connected", file=sys.stderr)

            session = await self._stack.enter_async_context(ClientSession(read, write))
            print(f"{server_name}: session created", file=sys.stderr)

            print(f"{server_name}: initializing...", file=sys.stderr)
            await session.initialize()
            print(f"{server_name}: initialized", file=sys.stderr)

            self._sessions[server_name] = session

            print(f"{server_name}: listing tools...", file=sys.stderr)
            listed = await session.list_tools()
            print(f"{server_name}: tools listed", file=sys.stderr)

            for tool in listed.tools:
                namespaced = f"{server_name}.{tool.name}"
                self.tools[namespaced] = ToolInfo(
                    server=server_name,
                    name=namespaced,
                    raw_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                )

    async def call_tool(self, namespaced_name: str, arguments: dict) -> str:
        info = self.tools.get(namespaced_name)
        if info is None:
            return f"Error: unknown tool '{namespaced_name}'."

        print(f"[mcp_manager] calling {namespaced_name} on server '{info.server}'...", file=sys.stderr)
        session = self._sessions[info.server]
        result = await session.call_tool(info.raw_name, arguments or {})
        print(f"[mcp_manager] got result back from {namespaced_name}", file=sys.stderr)

        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        text = "\n".join(parts)

        if result.isError:
            return f"Tool error: {text}"
        return text

    def tool_list_for_ui(self) -> list[dict]:
        return [
            {"server": t.server, "name": t.name, "description": t.description}
            for t in self.tools.values()
        ]

    async def close(self):
        await self._stack.aclose()