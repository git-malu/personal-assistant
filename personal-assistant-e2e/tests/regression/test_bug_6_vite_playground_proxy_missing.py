"""Regression test for bug-6: Vite Dev Server Does Not Proxy /playground.

Related: personal-assistant-meta/issues/bugs/bug-6-vite-playground-proxy-missing/

Bug: Vite dev server (port 5173) only proxies /api to the FastAPI backend,
not /playground. Visiting localhost:5173/playground serves the assistant-ui
SPA instead of Chainlit. This test verifies the proxy rule exists and works.
"""

import subprocess
import time
from pathlib import Path

import httpx
import pytest


# Project paths
_PROJ_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CLIENT_DIR = _PROJ_ROOT / "personal-assistant-client"
_SERVICE_DIR = _PROJ_ROOT / "personal-assistant-service"


def _get_uv_path() -> str:
    uv_path = _SERVICE_DIR / ".venv" / "bin" / "uv"
    if uv_path.exists():
        return str(uv_path)
    return "uv"


class ClientDevProcess:
    """Manage a subprocess running the Vite dev server."""

    def __init__(self, port: int = 5173):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, timeout: float = 30.0):
        """Start the Vite dev server."""
        self.process = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(self.port)],
            cwd=str(_CLIENT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
            f"Vite dev server did not become ready within {timeout}s on port {self.port}"
        )

    def stop(self):
        """Stop the dev server subprocess."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None


class ServiceProcess:
    """Manage a subprocess running the uvicorn server (backend)."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, env: dict[str, str] | None = None, timeout: float = 60.0):
        """Start the service in a subprocess."""
        import os

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        self.process = subprocess.Popen(
            [
                _get_uv_path(),
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "error",
            ],
            cwd=str(_SERVICE_DIR),
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    f"Service exited with code {self.process.returncode}: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                resp = httpx.get(f"{self.url}/api/ping", timeout=2.0)
                if resp.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(
            f"Service did not become healthy within {timeout}s on port {self.port}"
        )

    def stop(self):
        """Stop the service subprocess."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None


@pytest.mark.regression
@pytest.mark.slow
class TestBug6_VitePlaygroundProxyMissing:
    """Verify /playground is proxied from Vite dev server to Chainlit backend.

    BUG-6: When the Vite dev server does NOT proxy /playground to the backend,
    visiting localhost:<vite_port>/playground returns the assistant-ui SPA
    (index.html with <div id="root">) instead of Chainlit.
    """

    SERVICE_PORT = 18730
    VITE_PORT = 18731

    @pytest.fixture
    def dev_urls(self):
        """Start both the backend service and Vite dev server, returning their URLs.

        The Vite dev server must be started AFTER the backend to ensure the
        proxy target is available.
        """
        service = ServiceProcess(port=self.SERVICE_PORT)
        client = ClientDevProcess(port=self.VITE_PORT)

        try:
            service.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})

            # Ensure Vite config has /playground proxy pointing to our service.
            # If the proxy rule is correctly added (the fix), /playground
            # requests to the Vite dev server should be forwarded to the
            # backend's Chainlit mount.
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
        """GET /playground on Vite dev server should proxy to Chainlit.

        Before fix: Vite SPA fallback catches /playground and returns
        index.html (assistant-ui, contains '<div id="root">').
        After fix: request is proxied to FastAPI, which returns a redirect
        to /playground/ where Chainlit serves its HTML UI.
        """
        resp = httpx.get(
            f"{dev_urls['vite_url']}/playground",
            follow_redirects=False,
        )

        # The proxy should forward to the backend, which redirects /playground
        # to /playground/ (Chainlit mount requires trailing slash).
        # Accept 200 (Chainlit served directly) or 302/307 (redirect).
        assert resp.status_code in (200, 302, 307), (
            f"Expected /playground on Vite dev server to reach backend Chainlit, "
            f"got status {resp.status_code}"
        )

        # Key assertion: response must NOT be the assistant-ui SPA.
        # The SPA's index.html contains '<div id="root">' — if we see this,
        # the Vite SPA fallback intercepted the request (bug present).
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            assert "<div id=\"root\">" not in resp.text, (
                "FAIL: /playground on Vite dev server returned assistant-ui SPA "
                "(contains <div id=\"root\">). The Vite proxy for /playground is "
                "NOT configured — the SPA fallback is catching the path."
            )

    def test_playground_trailing_slash_on_vite_works(self, dev_urls):
        """GET /playground/ on Vite dev server should reach Chainlit HTML UI."""
        resp = httpx.get(f"{dev_urls['vite_url']}/playground/")

        assert resp.status_code == 200, (
            f"Expected 200 from /playground/ on Vite dev server, got {resp.status_code}"
        )
        assert "text/html" in resp.headers.get("content-type", "")

        # Should contain Chainlit markers, not SPA markers
        assert "<div id=\"root\">" not in resp.text, (
            "FAIL: /playground/ on Vite dev server returned the assistant-ui SPA "
            "instead of Chainlit HTML. The proxy is NOT forwarding to the backend."
        )

    # ── Sanity checks ─────────────────────────────────────────────────

    def test_api_proxy_still_works(self, dev_urls):
        """Sanity: /api/ping proxy (existing rule) should still work."""
        resp = httpx.get(f"{dev_urls['vite_url']}/api/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_root_still_serves_spa(self, dev_urls):
        """Sanity: GET / on Vite dev server should still serve the SPA."""
        resp = httpx.get(f"{dev_urls['vite_url']}/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "<div id=\"root\">" in resp.text, (
            "Sanity check failed: Vite root path does NOT serve the SPA."
        )

    def test_playground_ws_proxied(self, dev_urls):
        """WebSocket upgrade to /playground/ws should be forwarded to Chainlit.

        Chainlit uses WebSocket at /playground/ws for real-time communication.
        The proxy rule must include `ws: true` to support the protocol upgrade.
        """
        # Test that the endpoint at least accepts the WebSocket upgrade attempt
        # (returns 426 Upgrade Required or similar) rather than returning SPA HTML.
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{dev_urls['vite_url']}/playground/ws",
                    headers={
                        "Upgrade": "websocket",
                        "Connection": "Upgrade",
                    },
                )
                # A successful WebSocket handshake would be 101. If the proxy
                # is working but ws upgrade fails for other reasons (e.g., no
                # Chainlit session), we should at least not get SPA HTML back.
                if "text/html" in resp.headers.get("content-type", ""):
                    assert "<div id=\"root\">" not in resp.text, (
                        "FAIL: /playground/ws WebSocket upgrade was caught by "
                        "Vite SPA fallback. The proxy does not handle /playground "
                        "WebSocket connections."
                    )
        except httpx.RemoteProtocolError:
            # This is expected if the connection is handled as WebSocket
            # but our httpx client can't complete the handshake.
            pass
