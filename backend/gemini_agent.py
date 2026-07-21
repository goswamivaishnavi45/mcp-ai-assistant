"""
The "brain" of the assistant. Wraps the Gemini API and does the
function-calling loop against whatever tools MCPManager has
discovered. Gemini decides *which* tools to call and with what
arguments; this module just executes that loop.
"""
import os
import sys
from typing import Any

from google import genai
from google.genai import types

from mcp_manager import MCPManager

MAX_TOOL_ROUNDS = 6

SYSTEM_INSTRUCTION = (
    "You are a helpful AI assistant with access to external tools "
    "through the Model Context Protocol (MCP). You can search the "
    "web for current information and read/write files in a sandboxed "
    "workspace. Use tools whenever they would make your answer more "
    "accurate or complete. After you receive a tool result, use it to "
    "answer directly — only call the same tool again if the previous "
    "result was clearly insufficient or errored. Always explain, in "
    "plain language, what you did and why. Be concise."
)


def _clean_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema

    allowed_keys = {
        "type", "properties", "required", "items", "description",
        "enum", "format", "nullable",
    }
    cleaned = {}
    for key, value in schema.items():
        if key not in allowed_keys:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: _clean_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            cleaned[key] = _clean_schema(value)
        else:
            cleaned[key] = value

    cleaned.setdefault("type", "object")
    if cleaned["type"] == "object":
        cleaned.setdefault("properties", {})
    return cleaned


class GeminiAgent:
    def __init__(self, mcp_manager: MCPManager):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy backend/.env.example to "
                "backend/.env and add your key."
            )
        self.model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = genai.Client(api_key=api_key)
        self.mcp = mcp_manager

    def _build_tools(self) -> list[types.Tool]:
        declarations = []
        for tool in self.mcp.tools.values():
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name.replace(".", "__"),
                    description=f"[{tool.server} server] {tool.description}",
                    parameters=_clean_schema(tool.input_schema),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    async def chat(self, message: str, history: list[dict]) -> dict:
        contents: list[types.Content] = []
        for turn in history:
            contents.append(
                types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])])
            )
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

        tools = self._build_tools()
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools,
        )

        name_lookup = {t.name.replace(".", "__"): t.name for t in self.mcp.tools.values()}
        tool_call_log = []

        for round_num in range(MAX_TOOL_ROUNDS):
            print(f"[agent] round {round_num}: calling Gemini...", file=sys.stderr)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            print(f"[agent] round {round_num}: Gemini responded", file=sys.stderr)

            candidate = response.candidates[0]

            if candidate.content is None:
                print(
                    f"[agent] round {round_num}: Gemini returned no content "
                    f"(finish_reason={candidate.finish_reason})",
                    file=sys.stderr,
                )
                return {
                    "reply": (
                        f"Gemini returned no content (finish_reason: "
                        f"{candidate.finish_reason}). Try rephrasing."
                    ),
                    "tool_calls": tool_call_log,
                }

            function_calls = [
                part.function_call
                for part in candidate.content.parts
                if getattr(part, "function_call", None)
            ]

            if not function_calls:
                final_text = "".join(
                    part.text for part in candidate.content.parts if getattr(part, "text", None)
                )
                print(f"[agent] round {round_num}: final answer, no more tool calls", file=sys.stderr)
                return {"reply": final_text.strip(), "tool_calls": tool_call_log}

            print(
                f"[agent] round {round_num}: Gemini wants to call "
                f"{[fc.name for fc in function_calls]}",
                file=sys.stderr,
            )

            contents.append(candidate.content)

            response_parts = []
            for fc in function_calls:
                mcp_name = name_lookup.get(fc.name, fc.name)
                args = dict(fc.args) if fc.args else {}

                print(f"[agent] executing tool: {mcp_name} args={args}", file=sys.stderr)
                result_text = await self.mcp.call_tool(mcp_name, args)
                print(f"[agent] tool result received, length={len(result_text)}", file=sys.stderr)

                tool_call_log.append({"tool": mcp_name, "args": args, "result": result_text})

                response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_text},
                    )
                )

            contents.append(types.Content(role="user", parts=response_parts))
            print(f"[agent] round {round_num}: tool result appended, looping back to Gemini", file=sys.stderr)

        print("[agent] hit MAX_TOOL_ROUNDS without a final answer", file=sys.stderr)
        return {
            "reply": "I made several tool calls but couldn't reach a final answer in time. "
                     "Try rephrasing your request.",
            "tool_calls": tool_call_log,
        }