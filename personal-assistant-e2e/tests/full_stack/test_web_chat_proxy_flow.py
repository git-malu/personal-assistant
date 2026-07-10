"""Full-stack smoke for the local Web Chat proxy boundary.

This file intentionally stays small: detailed /invocations behavior belongs to
Service tests, while browser rendering belongs to browser tests.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from conftest import PROJECT_ROOT, ServiceProcess, terminate_process_tree

CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"

pytestmark = [pytest.mark.full_stack, pytest.mark.feature, pytest.mark.slow]


def _node_command() -> str:
    return shutil.which("node.exe") or shutil.which("node") or "node"


def _vite_cli_path() -> Path:
    return CLIENT_DIR / "node_modules" / "vite" / "bin" / "vite.js"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ClientDevProcess:
    """Manage a subprocess running the Vite dev server."""

    def __init__(self, *, port: int, service_url: str):
        self.port = port
        self.service_url = service_url
        self.process: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, timeout: float = 60.0) -> None:
        vite_cli = _vite_cli_path()
        if not vite_cli.exists():
            raise RuntimeError(f"Vite CLI not found at {vite_cli}")

        self.process = subprocess.Popen(
            [
                _node_command(),
                str(vite_cli),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(CLIENT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "BROWSER": "none",
                "PA_SERVICE_PROXY_TARGET": self.service_url,
            },
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    "Vite dev server exited with code "
                    f"{self.process.returncode}: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                resp = httpx.get(self.url, timeout=2.0)
                if resp.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(f"Vite dev server did not become ready on port {self.port}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            terminate_process_tree(self.process)
        self.process = None


@pytest.fixture
def dev_stack():
    """Start Service on the Vite proxy target port and then Vite."""
    service = ServiceProcess(port=_find_free_port())
    client = ClientDevProcess(port=_find_free_port(), service_url=service.url)

    try:
        service.start()
        client.start()
        yield {
            "service_url": service.url,
            "vite_url": client.url,
        }
    finally:
        client.stop()
        service.stop()


def test_vite_serves_spa_and_proxies_invocations(dev_stack):
    """Vite root serves the Client and /invocations reaches the Service."""
    with httpx.Client(timeout=10.0) as client:
        root = client.get(f"{dev_stack['vite_url']}/")
        assert root.status_code == 200
        assert "text/html" in root.headers.get("content-type", "")
        assert "@vite/client" in root.text

        proxied = client.post(
            f"{dev_stack['vite_url']}/invocations",
            json={"message": "", "stream": True},
            headers={
                "Accept": "text/event-stream",
                "x-hw-agentarts-session-id": "full-stack-proxy-session",
            },
        )
        assert proxied.status_code == 400
        assert proxied.json()["detail"] == "message is required"


def test_vite_proxies_invocations_playground(dev_stack):
    """The Vite same-origin path reaches the Service playground mount."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{dev_stack['vite_url']}/invocations/playground",
            follow_redirects=False,
        )

    assert resp.status_code in (302, 307)
    assert resp.headers.get("location") == "/invocations/playground/"
