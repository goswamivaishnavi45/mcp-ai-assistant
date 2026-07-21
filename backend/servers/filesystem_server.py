"""
MCP server: sandboxed filesystem tools.

Exposes read/write/list/mkdir tools that are locked to a single
"workspace" directory, so the AI can never touch files outside of it.

Run standalone for testing:
    python filesystem_server.py
It speaks MCP over stdio, so it's normally launched as a subprocess
by the backend (see mcp_manager.py), not run directly by a human.
"""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Everything this server touches is confined to this directory.
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent / "workspace"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("filesystem")


def _resolve_safe(relative_path: str) -> Path:
    """Resolve a user-supplied relative path and guarantee it stays
    inside WORKSPACE_ROOT. Raises ValueError if someone tries to
    escape the sandbox (e.g. via '../../etc/passwd')."""
    candidate = (WORKSPACE_ROOT / relative_path).resolve()
    if WORKSPACE_ROOT not in candidate.parents and candidate != WORKSPACE_ROOT:
        raise ValueError(
            f"Path '{relative_path}' escapes the sandboxed workspace directory."
        )
    return candidate


@mcp.tool()
def list_files(path: str = ".") -> str:
    """List files and directories inside the sandboxed workspace.

    Args:
        path: Relative path inside the workspace to list. Defaults to
            the workspace root.
    """
    target = _resolve_safe(path)
    if not target.exists():
        return f"Error: '{path}' does not exist."
    if not target.is_dir():
        return f"Error: '{path}' is not a directory."

    entries = []
    for item in sorted(target.iterdir()):
        kind = "dir" if item.is_dir() else "file"
        entries.append(f"{kind}\t{item.relative_to(WORKSPACE_ROOT)}")
    return "\n".join(entries) if entries else "(empty directory)"


@mcp.tool()
def read_file(path: str) -> str:
    """Read the full text contents of a file in the sandboxed workspace.

    Args:
        path: Relative path to the file inside the workspace.
    """
    target = _resolve_safe(path)
    if not target.exists():
        return f"Error: '{path}' does not exist."
    if not target.is_file():
        return f"Error: '{path}' is not a file."
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: '{path}' is not a readable text file."


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with the given text content, inside
    the sandboxed workspace. Parent directories are created automatically.

    Args:
        path: Relative path to the file inside the workspace.
        content: Text content to write to the file.
    """
    target = _resolve_safe(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to '{path}'."


@mcp.tool()
def create_directory(path: str) -> str:
    """Create a new directory (including parent directories) inside
    the sandboxed workspace.

    Args:
        path: Relative path of the directory to create.
    """
    target = _resolve_safe(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory '{path}'."


@mcp.tool()
def delete_path(path: str) -> str:
    """Delete a file (or empty directory) inside the sandboxed workspace.

    Args:
        path: Relative path to delete.
    """
    target = _resolve_safe(path)
    if not target.exists():
        return f"Error: '{path}' does not exist."
    if target.is_dir():
        try:
            target.rmdir()
        except OSError:
            return f"Error: '{path}' is a non-empty directory."
    else:
        target.unlink()
    return f"Deleted '{path}'."


if __name__ == "__main__":
    mcp.run()
