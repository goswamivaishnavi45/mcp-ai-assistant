# MCP-Powered AI Assistant (Gemini)

A small web app that demonstrates the Model Context Protocol (MCP):
Gemini acts as the reasoning engine, and dynamically discovers and
calls tools exposed by separate MCP servers — no hardcoded "if user
says X, call function Y" logic. Add a new MCP server and its tools
show up automatically, with zero changes to the agent code.

**Included MCP servers**
- `websearch` — searches the web via DuckDuckGo (no API key needed)
- `filesystem` — read/write/list files, sandboxed to a `workspace/` folder

## How it fits together

```
Browser (chat UI)
      │  POST /api/chat
      ▼
FastAPI backend (app.py)
      │
      ▼
GeminiAgent  ──function-calling loop──►  Gemini API
      │
      ▼
MCPManager  ──stdio──►  filesystem_server.py  (subprocess)
      │      ──stdio──►  websearch_server.py   (subprocess)
```

Each MCP server is a separate subprocess speaking the MCP protocol
over stdio. `MCPManager` connects to all of them at startup, asks
each one to list its tools, and merges everything into one flat,
namespaced registry (`filesystem.read_file`, `websearch.search_web`,
...). `GeminiAgent` converts that registry into Gemini function
declarations on every request, so tools are always discovered live,
never hardcoded.

## Setup

1. **Python 3.10+** required.

2. Create a virtual environment and install dependencies:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Add your Gemini API key:
   ```bash
   cp .env.example .env
   ```
   Edit `backend/.env` and paste your key from
   https://aistudio.google.com/apikey into `GEMINI_API_KEY`.

4. Run the server:
   ```bash
   python app.py
   ```
   (from inside `backend/`, with the venv active)

5. Open **http://localhost:8003** in your browser.

That's it — no separate frontend build step, no Node.js required.
FastAPI serves the chat UI directly.

## Trying it out

- "What's the latest news about the James Webb telescope?" → triggers `websearch.search_web`
- "Create a file called notes.md with a short poem about the ocean, then read it back to me" → triggers `filesystem.write_file` then `filesystem.read_file`
- "List everything in my workspace" → triggers `filesystem.list_files`

Watch the left panel: each tool node lights up briefly when Gemini
calls it, and the tool call (name + arguments) is shown inline in the
chat as a dashed trace box.

## Extending it

To add a new tool/server:
1. Write a new MCP server file in `backend/servers/` using
   `mcp.server.fastmcp.FastMCP` (copy `websearch_server.py` as a
   template — it's the shortest one).
2. Register it in `SERVER_CONFIGS` in `backend/mcp_manager.py`.
3. Restart the app. No other code changes needed — Gemini will see
   the new tool automatically.

## Notes & limitations (by design, for clarity as a learning project)

- Conversation history persisted between turns is text-only (final
  answers). Intermediate tool calls are re-derived fresh each turn
  rather than replayed from history, to keep the wire format simple.
- The filesystem tool is intentionally sandboxed to `workspace/` and
  will refuse any path that resolves outside it.
- `MAX_TOOL_ROUNDS` in `gemini_agent.py` caps how many tool-call
  rounds one message can trigger, so a confused model can't loop
  forever.


## A real debugging story: the silent hang

While testing the web search tool, tool calls would consistently hang
forever with no error — the MCP subprocess would print its final log
line ("returning formatted results") but the parent process never
received the response.

**Isolating it:** I added stderr logging at every stage of the
pipeline (tool execution, MCP transport, Gemini round-trips) to
narrow down exactly where execution stopped. This ruled out Tavily,
Gemini, and the agent loop — the response was being *written* by the
subprocess but never *received* by the parent.

**Root cause #1 — buffering:** On Windows, a subprocess's stdout
defaults to block buffering when redirected to a pipe (instead of
line buffering, which is the default in an interactive terminal).
MCP communicates over exactly this kind of pipe, so responses could
sit in an internal buffer indefinitely. Fixed by launching the
subprocess with Python's `-u` (unbuffered) flag.

**Root cause #2 — encoding:** Even after fixing buffering, real web
search results (containing e.g. `°`, curly quotes, em dashes) still
hung. Windows subprocesses default to a legacy codepage (not UTF-8)
for stdio. Writing non-ASCII characters into a pipe expecting that
legacy encoding can silently fail inside the child process, with no
traceback surfaced to the parent — it just stops. Fixed by explicitly
setting `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` in the
subprocess's environment.

**Lesson:** silent hangs (vs. exceptions) are usually an I/O boundary
problem — buffering, encoding, or a blocked pipe — not a logic bug.
Instrumenting each hop with timestamps/logs is the fastest way to
isolate exactly which boundary is failing.