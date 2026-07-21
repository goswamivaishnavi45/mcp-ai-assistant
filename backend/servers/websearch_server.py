from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient
from dotenv import load_dotenv
import os

load_dotenv()
import sys
mcp = FastMCP("websearch")



@mcp.tool()
def search_web(query: str, num_results: int = 5) -> str:
    from tavily import TavilyClient
    import os
    import sys

    print("search_web called", file=sys.stderr)
    print(f"query={query!r} num_results={num_results!r}", file=sys.stderr)

    api_key = os.getenv("TAVILY_API_KEY")
    print(f"TAVILY_API_KEY loaded: {bool(api_key)}", file=sys.stderr)

    client = TavilyClient(api_key=api_key)

    print("calling tavily...", file=sys.stderr)
    try:
        response = client.search(
            query=query,
            max_results=num_results,
            search_depth="basic",
        )
    except Exception as exc:
        print(f"tavily raised an exception: {exc!r}", file=sys.stderr)
        return f"Search failed: {exc}"

    print("tavily returned", file=sys.stderr)

    results = response.get("results", [])

    print(f"got {len(results)} results", file=sys.stderr)

    if not results:
        return "No results found."
    def _clean_text(s: str) -> str:
        # Collapse any newlines/control chars inside a single field so they
        # can't break the newline-delimited JSON-RPC framing over stdio.
        return " ".join(s.split())

    out = []
    for i, r in enumerate(results, 1):
        title = _clean_text(r.get('title', ''))
        url = r.get('url', '')
        content = _clean_text(r.get('content', ''))
        out.append(f"{i}. {title}\n{url}\n{content}")

    result_str = "\n\n".join(out)
    print(f"about to return {len(result_str)} characters", file=sys.stderr)
    return result_str




if __name__ == "__main__":
    import sys
    print("Starting WebSearch MCP Server", file=sys.stderr)
    mcp.run()