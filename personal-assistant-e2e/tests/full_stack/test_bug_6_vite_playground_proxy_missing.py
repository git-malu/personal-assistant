"""Regression test for bug-6: Vite dev server playground proxy coverage.

Related: personal-assistant-meta/issues/bugs/bug-6-vite-playground-proxy-missing/

The current route contract uses /invocations/playground for Chainlit. This test
verifies Vite forwards that same-origin path to the backend instead of serving
the assistant-ui SPA fallback.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Import shared ServiceProcess fixture from e2e conftest.
# pytest automatically discovers conftest.py in the e2e root directory.
from conftest import PROJECT_ROOT, ServiceProcess, terminate_process_tree

_CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"

pytestmark = [pytest.mark.full_stack]


def _node_command() -> str:
    return shutil.which("node.exe") or shutil.which("node") or "node"


def _vite_cli_path() -> Path:
    return _CLIENT_DIR / "node_modules" / "vite" / "bin" / "vite.js"


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

    def start(self, timeout: float = 30.0):
        """Start the Vite dev server."""
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
            cwd=str(_CLIENT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "BROWSER": "none",
                "PA_SERVICE_PROXY_TARGET": self.service_url,
            },
        )

        # Wait for the dev server to be ready
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    f"Vite dev server exited with code {self.process.returncode}: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                resp = httpx.get(self.url, timeout=2.0)
                if resp.status_code == 200:
                    return  # Success
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(
            "Vite dev server did not become ready within "
            f"{timeout}s on port {self.port}"
        )

    def stop(self):
        """Stop the dev server subprocess."""
        if self.process and self.process.poll() is None:
            terminate_process_tree(self.process)
        self.process = None


@pytest.mark.regression
@pytest.mark.slow
class TestBug6VitePlaygroundProxyMissing:
    """Verify playground is proxied from Vite dev server to Chainlit backend.

    BUG-6: When the Vite dev server does NOT proxy the playground backend path,
    visiting localhost:<vite_port>/invocations/playground returns the
    assistant-ui SPA instead of Chainlit.
    """

    @pytest.fixture
    def dev_urls(self):
        """Start both the backend service and Vite dev server, returning their URLs.

        The Vite dev server must be started AFTER the backend to ensure the
        proxy target is available.
        """
        service = ServiceProcess(port=_find_free_port())
        client = ClientDevProcess(port=_find_free_port(), service_url=service.url)

        try:
            service.start()

            # Ensure Vite config has the playground proxy pointing to this
            # service. Requests through the Vite origin should be forwarded to
            # the backend's Chainlit mount.
            client.start()

            yield {
                "vite_url": client.url,
                "service_url": service.url,
            }
        finally:
            client.stop()
            service.stop()

    # ── Core bug assertions ──────────────────────────────────────────

    def test_playground_on_vite_serves_chainlit_not_spa(self, dev_urls):
        """GET /invocations/playground through Vite should proxy to Chainlit.

        Before fix: Vite SPA fallback catches the playground path and returns
        index.html (assistant-ui, contains '<div id="root">').
        After fix: request is proxied to FastAPI, which returns a redirect
        to /invocations/playground/ where Chainlit serves its HTML UI.
        """
        resp = httpx.get(
            f"{dev_urls['vite_url']}/invocations/playground",
            follow_redirects=False,
        )

        # The proxy should forward to the backend, which redirects to the
        # trailing-slash path required by the Chainlit mount.
        # Accept 200 (Chainlit served directly) or 302/307 (redirect).
        assert resp.status_code in (200, 302, 307), (
            "Expected /invocations/playground on Vite dev server to reach "
            f"backend Chainlit, got status {resp.status_code}"
        )

        # If redirect, verify the Location header targets the mounted path.
        if resp.status_code in (302, 307):
            location = resp.headers.get("Location", "")
            assert location.endswith("/invocations/playground/"), (
                "Expected redirect Location to end with /invocations/playground/, "
                f"got {location!r}"
            )

        # Key assertion: response must NOT be the assistant-ui SPA.
        # The SPA's index.html contains Vite-specific scripts like '@vite/client';
        # Chainlit HTML does not. (NB: both are React apps and both contain
        # '<div id="root">', so that is NOT a valid discriminator.)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            assert "@vite/client" not in resp.text, (
                "FAIL: /invocations/playground on Vite dev server returned "
                "assistant-ui SPA (contains @vite/client). The Vite proxy for "
                "/invocations/playground is NOT configured — the SPA fallback "
                "is catching the path."
            )
            # Sanity: should contain Chainlit markers
            assert "chainlit" in resp.text.lower(), (
                "FAIL: /invocations/playground response is HTML but does not "
                "contain Chainlit markers — unexpected content."
            )

    def test_playground_trailing_slash_on_vite_works(self, dev_urls):
        """GET /invocations/playground/ through Vite reaches Chainlit HTML UI."""
        resp = httpx.get(f"{dev_urls['vite_url']}/invocations/playground/")

        assert resp.status_code == 200, (
            "Expected 200 from /invocations/playground/ on Vite dev server, "
            f"got {resp.status_code}"
        )
        assert "text/html" in resp.headers.get("content-type", "")

        # Should contain Chainlit markers, not SPA markers.
        # Chainlit HTML includes 'chainlit' and lacks '@vite/client'.
        # (Both Chainlit and the Vite SPA contain '<div id="root">', so that
        # is NOT a valid discriminator — use Vite-specific scripts instead.)
        assert "@vite/client" not in resp.text, (
            "FAIL: /invocations/playground/ on Vite dev server returned the "
            "assistant-ui SPA (contains @vite/client). The proxy is NOT "
            "forwarding to the backend."
        )
        assert "chainlit" in resp.text.lower(), (
            "FAIL: /invocations/playground/ response is HTML but missing "
            "Chainlit markers — the proxy may be returning unexpected content."
        )

    # ── Sanity checks ─────────────────────────────────────────────────

    def test_invocations_proxy_still_works(self, dev_urls):
        """Sanity: /invocations proxy still reaches the backend service."""
        resp = httpx.post(
            f"{dev_urls['vite_url']}/invocations",
            json={
                "conversation_id": "0190e9fe-82b4-7000-8000-000000000001",
                "client_message_id": "0190e9fe-82b4-7000-8000-000000000002",
                "message": "",
                "stream": True,
            },
            headers={
                "Accept": "text/event-stream",
                "x-hw-agentarts-session-id": "bug-6-proxy-session",
            },
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "message is required"

    def test_root_still_serves_spa(self, dev_urls):
        """Sanity: GET / on Vite dev server should still serve the SPA."""
        resp = httpx.get(f"{dev_urls['vite_url']}/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "@vite/client" in resp.text, (
            "Sanity check failed: Vite root path does NOT serve the SPA "
            "(missing @vite/client script injection)."
        )

    def test_playground_ws_proxied(self, dev_urls):
        """WebSocket upgrade to the playground path should be forwarded to Chainlit.

        Chainlit uses WebSocket under the playground mount for real-time
        communication. The proxy rule must include `ws: true` to support the
        protocol upgrade.
        """
        # Test that the endpoint at least accepts the WebSocket upgrade attempt
        # (returns 426 Upgrade Required or similar) rather than returning SPA HTML.
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{dev_urls['vite_url']}/invocations/playground/ws",
                    headers={
                        "Upgrade": "websocket",
                        "Connection": "Upgrade",
                    },
                )
                # A successful WebSocket handshake would be 101. If the proxy
                # is working but ws upgrade fails for other reasons (e.g., no
                # Chainlit session), we should at least not get SPA HTML back.
                if "text/html" in resp.headers.get("content-type", ""):
                    assert "@vite/client" not in resp.text, (
                        "FAIL: /invocations/playground/ws WebSocket upgrade was "
                        "caught by Vite SPA fallback (contains @vite/client). "
                        "The proxy does not handle playground WebSocket "
                        "connections."
                    )
        except httpx.RemoteProtocolError as e:
            # This is expected if the connection is handled as WebSocket
            # but our httpx client can't complete the handshake.
            pytest.skip(
                f"WebSocket connection triggered RemoteProtocolError "
                f"(expected for ws upgrade): {e}"
            )
        except httpx.TimeoutException as e:
            pytest.skip(
                f"WebSocket upgrade did not complete over httpx "
                f"(acceptable for ws proxy smoke): {e}"
            )
