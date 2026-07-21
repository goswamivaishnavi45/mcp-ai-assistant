"""
FastAPI backend for the MCP-powered AI assistant.

Startup:  connect to all configured MCP servers, discover their tools.
Runtime:  POST /api/chat routes a user message through Gemini, which
          dynamically decides which MCP tools (if any) to call.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env")

from gemini_agent import GeminiAgent
from mcp_manager import MCPManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = MCPManager()
    await manager.connect_all()
    state["mcp_manager"] = manager
    state["agent"] = GeminiAgent(manager)
    print(f"[startup] Connected MCP tools: {list(manager.tools.keys())}")
    yield
    await manager.close()


app = FastAPI(title="MCP-Powered AI Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class HistoryTurn(BaseModel):
    role: str  # "user" or "model"
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryTurn] = []


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]


@app.get("/api/tools")
async def list_tools():
    manager: MCPManager = state["mcp_manager"]
    return {"tools": manager.tool_list_for_ui()}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    agent: GeminiAgent = state["agent"]
    history = [{"role": t.role, "text": t.text} for t in req.history]
    result = await agent.chat(req.message, history)
    return result


# --- Serve the frontend ---
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8003, reload=False)
