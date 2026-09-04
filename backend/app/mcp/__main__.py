"""Run the EASY BUY MCP server (ADR-024).

    python -m app.mcp                 # streamable-http on 127.0.0.1:8005 (default)
    python -m app.mcp --stdio         # stdio, for Claude Desktop / an MCP client config
    python -m app.mcp --port 9000     # another port

The server reuses the application's services and database, so the same
PostgreSQL and the same `.env` that the API uses must be reachable.
"""

from __future__ import annotations

import argparse
import logging

from app.logging_config import configure_logging
from app.mcp.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="EASY BUY MCP server")
    parser.add_argument("--stdio", action="store_true", help="use stdio transport")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8005)
    args = parser.parse_args()

    configure_logging(level="INFO", fmt="console", secrets=[])
    logging.getLogger(__name__).info(
        "starting EASY BUY MCP server",
        extra={"transport": "stdio" if args.stdio else "streamable-http"},
    )

    server = build_server()
    if args.stdio:
        server.run(transport="stdio")
    else:
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
