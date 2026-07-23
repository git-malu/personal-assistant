"""Regression test for bug-18: expired login token must sign out cleanly.

Related:
personal-assistant-meta/issues/bugs/bug-18-expired-login-token-not-logging-out/

The browser test runs the Vite client and mocks only the inbound MSAL token
lifecycle:
- initial hydration receives an already-expired ID token;
- the next silent refresh returns null;
- sending a chat message must not call /invocations with the expired token;
- the page must leave ChatPage and show the login entry again.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
_IS_WINDOWS = os.name == "nt"

pytestmark = [pytest.mark.regression, pytest.mark.browser, pytest.mark.slow]


class ClientDevProcess:
    """Manage a subprocess running the Vite dev server."""

    def __init__(self, port: int = 18732):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, timeout: float = 30.0) -> None:
        command = [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--strictPort",
        ]
        if _IS_WINDOWS:
            command[0] = "npm.cmd"
        self.process = subprocess.Popen(
            command,
            cwd=str(CLIENT_DIR),
            env={
                **os.environ,
                "VITE_ENTRA_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "VITE_ENTRA_TENANT_ID": "common",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    f"Vite dev server exited with code "
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
        raise TimeoutError("Vite dev server did not become ready")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if _IS_WINDOWS:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process -Filter \"name = 'node.exe'\" "
                        f"| Where-Object {{ $_.CommandLine -like '*{CLIENT_DIR.name}*' "
                        f"-and $_.CommandLine -like '*{self.port}*' }} "
                        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
                    ),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self.process = None


@pytest.fixture
def vite_url():
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip(
            "node_modules/ not found — run 'npm install' in personal-assistant-client/"
        )

    client = ClientDevProcess()
    client.start()
    try:
        yield client.url
    finally:
        client.stop()


def _expired_jwt_patch() -> str:
    return """
let __bug18AcquireCalls = 0;
function __bug18ExpiredJwt() {
  const payload = btoa(JSON.stringify({
    exp: Math.floor(Date.now() / 1000) - 3600,
    sub: "bug18-user",
  }));
  return `header.${payload}.signature`;
}

export async function acquireIdTokenSilently() {
  __bug18AcquireCalls += 1;
  return __bug18AcquireCalls === 1 ? __bug18ExpiredJwt() : null;
}
"""


def _handle_auth_route(route):
    """Patch auth.ts so hydration gets an expired token and refresh fails."""
    resp = route.fetch()
    body = resp.text()
    body = re.sub(
        r"export async function acquireIdTokenSilently\(\) \{.*?\n\}\n"
        r"export async function clearInboundAuthSession",
        _expired_jwt_patch() + "\nexport async function clearInboundAuthSession",
        body,
        flags=re.S,
    )
    route.fulfill(status=resp.status, headers=dict(resp.headers), body=body)


def _handle_app_route(route):
    """Patch App.tsx so MSAL appears authenticated during the regression."""
    resp = route.fetch()
    body = resp.text()
    body = body.replace(
        "const isAuthenticated = useIsAuthenticated();",
        "const isAuthenticated = true; // bug-18 E2E MSAL mock",
    )
    route.fulfill(status=resp.status, headers=dict(resp.headers), body=body)


def test_bug_18_expired_token_refresh_failure_signs_out_without_invocation(
    vite_url,
):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")

    invocation_requests: list[dict[str, str]] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Playwright Chromium is unavailable: {exc}")

        context = browser.new_context()
        page = context.new_page()
        try:
            page.route(lambda url: "/src/lib/auth.ts" in url, _handle_auth_route)
            page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

            def _capture_invocations(route):
                request = route.request
                invocation_requests.append(dict(request.headers))
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body='{"error":"expired token should not be sent"}',
                )

            page.route("**/invocations", _capture_invocations)

            page.goto(vite_url, timeout=30000)
            page.wait_for_selector("text=Personal Assistant", timeout=15000)
            # The Conversation warm-up request performs proactive refresh and
            # signs out before an Invocation can carry the expired token.
            page.wait_for_selector("text=您的 AI 助手", timeout=15000)

            assert invocation_requests == [], (
                "BUG-18 regression: expired ID token was still sent to /invocations"
            )
            assert not page.locator("textarea.aui-composer-input").is_visible(), (
                "BUG-18 regression: ChatPage stayed visible after auth expiry"
            )
        finally:
            context.close()
            browser.close()
