"""Run the E2E Service with an async loop compatible with psycopg on Windows."""

import argparse
import asyncio
import os
import selectors
import sys

import uvicorn


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log-level", default="error")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    application = os.getenv("PA_E2E_ASGI_APP", "app.main:app")
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host=arguments.host,
            port=arguments.port,
            log_level=arguments.log_level,
        )
    )
    if os.name == "nt":
        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        return
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
