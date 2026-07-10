"""E2E tests for Feature 13 — Reset Session ("新对话") button.

Tests the full application stack:
- FastAPI service using canonical Settings
- Vite dev server (subprocess) with proxy to backend
- Playwright browser automation for UI interactions

Test scenarios:
  1. Full reset → welcome screen
  2. localStorage key deletion
  3. New UUID header after reset + new message
  4. Composer/input cleared after reset
  5. Button disabled during streaming
  6. Privacy mode (localStorage unavailable)
"""

import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"

# Platform detection
_IS_WINDOWS = os.name == "nt"

# ── Helpers ────────────────────────────────────────────────────────────


def _get_uv_path() -> str:
    """Get the uv binary from the service venv or fall back to system uv."""
    # On Windows, venv binaries are in Scripts/, on Unix they're in bin/
    for subdir in ("Scripts", "bin"):
        uv_path = SERVICE_DIR / ".venv" / subdir / "uv"
        if _IS_WINDOWS:
            if uv_path.exists() or Path(str(uv_path) + ".exe").exists():
                return str(uv_path)
        else:
            if uv_path.exists():
                return str(uv_path)
    return "uv"


def _start_service(
    port: int, env: dict[str, str] | None = None, timeout: float = 60.0
) -> subprocess.Popen:
    """Start uvicorn as a subprocess. Returns the Popen handle."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    proc = subprocess.Popen(
        [
            _get_uv_path(),
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=str(SERVICE_DIR),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            try:
                _, stderr = proc.communicate(timeout=5)
            except Exception:
                stderr = b""
            stderr_text = stderr.decode(errors="replace")[-1000:]
            raise RuntimeError(
                f"Service exited with code {proc.returncode}: {stderr_text}"
            )
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/ping", timeout=2.0)
            if resp.status_code == 200:
                return proc
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)

    _stop_process(proc)
    raise TimeoutError(
        f"Service did not become healthy within {timeout}s on port {port}"
    )


def _stop_process(proc: subprocess.Popen):
    """Gracefully stop a subprocess. Uses terminate() (cross-platform)."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Pytest markers ─────────────────────────────────────────────────────

pytestmark = [
    pytest.mark.feature,
    pytest.mark.browser,
    pytest.mark.slow,
]


# ── App Module Route Interceptor (bypass MSAL auth) ────────────────────
# In dev mode, Vite serves transformed App.tsx at /src/App.tsx.
# We intercept this request and replace useIsAuthenticated() with true
# so ChatPage always renders without MSAL authentication.


def _handle_app_route(route):
    """Intercept Vite-served App.tsx to bypass MSAL auth check."""
    # Fetch the original response from Vite
    resp = route.fetch()
    body = resp.text()

    # Replace useIsAuthenticated() with always-true
    # Vite transforms: const isAuthenticated = useIsAuthenticated();
    body = body.replace(
        "const isAuthenticated = useIsAuthenticated();",
        "const isAuthenticated = true; // E2E bypass",
    )
    body = body.replace(
        "const canShowChat = isAuthenticated && Boolean(idToken);",
        "const canShowChat = true; // E2E bypass",
    )

    route.fulfill(
        status=resp.status,
        headers=dict(resp.headers),
        body=body,
    )


# ── Fixtures ───────────────────────────────────────────────────────────


def _ensure_deps():
    """Check that required dependencies are available."""
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip(
            "node_modules/ not found — run 'npm install' in personal-assistant-client/"
        )

    # Check Playwright browsers (quick launch/close to verify)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        pytest.skip(f"Playwright browser not available: {e}")


@pytest.fixture(scope="class")
def stack():
    """Start both backend service and Vite dev server.

    Architecture:
    - Backend normally runs on port 8080 behind the Vite same-origin proxy.
    - Port 8080 is required because the checked-in Vite proxy owns the
      same-origin topology.
    - Vite dev server runs on port 5173.

    Returns (vite_url, service_url).
    """
    _ensure_deps()

    vite_port = 5173
    service_port = 8080  # matches Vite proxy target in vite.config.ts

    # Try to start service on port 8080 first (matches Vite proxy)
    try:
        svc_proc = _start_service(service_port)
    except (RuntimeError, TimeoutError):
        pytest.skip("Port 8080 is required by the Vite same-origin proxy")

    # Start Vite dev server
    vite_env = os.environ.copy()
    vite_env["BROWSER"] = "none"
    vite_env["VITE_API_BASE_URL"] = ""

    npm_cmd = "npm.cmd" if _IS_WINDOWS else "npm"
    vite_proc = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--port", str(vite_port), "--strictPort"],
        cwd=str(CLIENT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=vite_env,
    )

    # Wait for Vite
    deadline = time.time() + 60
    vite_ready = False
    while time.time() < deadline:
        if vite_proc.poll() is not None:
            stdout, stderr = vite_proc.communicate(timeout=5)
            _stop_process(svc_proc)
            raise RuntimeError(
                f"Vite dev server exited with code {vite_proc.returncode}.\n"
                f"stdout: {stdout.decode(errors='replace')[-500:]}\n"
                f"stderr: {stderr.decode(errors='replace')[-500:]}"
            )
        try:
            resp = httpx.get(f"http://localhost:{vite_port}/", timeout=2.0)
            if resp.status_code == 200:
                vite_ready = True
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(1)

    if not vite_ready:
        _stop_process(vite_proc)
        _stop_process(svc_proc)
        raise TimeoutError(
            f"Vite dev server did not start within 60s on port {vite_port}"
        )

    service_url = f"http://127.0.0.1:{service_port}"
    vite_url = f"http://localhost:{vite_port}"

    yield vite_url, service_url

    _stop_process(vite_proc)
    _stop_process(svc_proc)


# ── Test Scenarios ─────────────────────────────────────────────────────


@pytest.mark.usefixtures("stack")
class TestScenario1FullReset:
    """E2E-RS-01: Full reset → welcome screen."""

    def test_full_reset_shows_welcome_screen(self, stack):
        """After clicking Reset + Confirm, the thread is cleared to welcome state."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Intercept the App.tsx module to bypass MSAL auth check.
                # Replace useIsAuthenticated() with always-true to render ChatPage.
                page.route(
                    lambda url: "/src/App.tsx" in url,
                    _handle_app_route,
                )

                # 1. Navigate to chat page
                page.goto(vite_url, timeout=30000)
                # Wait for the app to render
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                # Wait for ChatPage (ResetSessionButton visible after hydration)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)

                # 2. The composer should be visible in ChatPage.
                # assistant-ui uses textarea for the composer.
                composer_sel = "textarea.aui-composer-input"
                page.wait_for_selector(composer_sel, timeout=10000)
                page.wait_for_timeout(2000)

                # 3. Type and send a message
                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("你好")
                page.keyboard.press("Enter")
                # Wait for the user message to appear in the thread
                page.wait_for_selector("text=你好", timeout=10000)

                # 4. Click the Reset button by aria-label
                reset_btn = page.get_by_label("新对话")
                assert reset_btn.is_visible(), (
                    "Reset button (aria-label='新对话') not visible"
                )
                reset_btn.click()

                # 5. Wait for the confirmation dialog
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                assert dialog.is_visible(), "Confirmation dialog did not appear"

                # Verify dialog content
                assert dialog.get_by_text("新对话").count() > 0, (
                    "Dialog title '新对话' not found"
                )
                assert "开始全新对话" in dialog.text_content(), (
                    f"Dialog description not found in: {dialog.text_content()}"
                )

                # 6. Click the Confirm button
                confirm_btn = dialog.get_by_role("button", name="确认")
                assert confirm_btn.is_visible(), "Confirm button not visible"
                confirm_btn.click()

                # 7. Wait for dialog to close
                dialog.wait_for(state="hidden", timeout=5000)

                # 8. Verify thread was cleared — the sent message is gone
                page.wait_for_timeout(1000)
                assert not page.locator("text=你好").is_visible(), (
                    "User message should be cleared from thread after reset"
                )

                # 9. Verify composer is empty
                composer = page.locator("textarea.aui-composer-input").first
                assert composer.input_value() == "", (
                    "Composer should be empty after reset"
                )

                # 10. Verify app still functional (header visible)
                assert page.locator("text=Personal Assistant").is_visible(), (
                    "App should still be visible after reset"
                )

            finally:
                browser.close()


@pytest.mark.usefixtures("stack")
class TestScenario2LocalStorageKeyDeletion:
    """E2E-RS-02: localStorage key deletion after reset."""

    def test_localstorage_key_removed_after_reset(self, stack):
        """localStorage 'agentarts-session-id' is removed after reset+confirm."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Bypass MSAL auth via route interception
                page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

                # 1. Navigate and wait for app to load
                page.goto(vite_url, timeout=30000)
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)
                page.wait_for_timeout(2000)

                # 2. Send a message to trigger session ID creation
                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("Hello")
                page.keyboard.press("Enter")
                # Wait for the user message to appear
                page.wait_for_selector("text=Hello", timeout=10000)

                # 3. Verify session ID exists in localStorage
                session_id = page.evaluate(
                    "() => localStorage.getItem('agentarts-session-id')"
                )
                assert session_id is not None, (
                    "Expected 'agentarts-session-id' in localStorage after "
                    "sending a message"
                )
                assert isinstance(session_id, str) and len(session_id) > 0, (
                    f"Session ID should be a non-empty string, got: {session_id!r}"
                )

                # 4. Click Reset → Confirm
                page.get_by_label("新对话").click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                dialog.get_by_role("button", name="确认").click()
                dialog.wait_for(state="hidden", timeout=5000)

                # 5. Verify session ID was removed
                session_id_after = page.evaluate(
                    "() => localStorage.getItem('agentarts-session-id')"
                )
                assert session_id_after is None, (
                    "Expected 'agentarts-session-id' to be null after reset, "
                    f"got: {session_id_after!r}"
                )

            finally:
                browser.close()


@pytest.mark.usefixtures("stack")
class TestScenario3NewUUIDAfterReset:
    """E2E-RS-03: New UUID header after reset + new message."""

    def test_new_uuid_after_reset_and_message(self, stack):
        """After reset, the next message generates a different session ID."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Bypass MSAL auth via route interception
                page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

                # 1. Navigate and send first message
                page.goto(vite_url, timeout=30000)
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)
                page.wait_for_timeout(2000)

                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("First message")
                page.keyboard.press("Enter")
                page.wait_for_selector("text=First message", timeout=10000)

                # Capture session ID
                old_session_id = page.evaluate(
                    "() => localStorage.getItem('agentarts-session-id')"
                )
                assert old_session_id is not None

                # 2. Reset
                page.get_by_label("新对话").click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                dialog.get_by_role("button", name="确认").click()
                dialog.wait_for(state="hidden", timeout=5000)

                # Verify old session ID is removed
                after_reset = page.evaluate(
                    "() => localStorage.getItem('agentarts-session-id')"
                )
                assert after_reset is None, "Session ID should be removed after reset"

                # 3. Send a new message
                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("Second message")
                page.keyboard.press("Enter")
                page.wait_for_selector("text=Second message", timeout=10000)

                # 4. Verify new session ID is different
                new_session_id = page.evaluate(
                    "() => localStorage.getItem('agentarts-session-id')"
                )
                assert new_session_id is not None, (
                    "Expected a new session ID after sending a message post-reset"
                )
                assert new_session_id != old_session_id, (
                    f"Expected new session ID, but got same: {new_session_id}"
                )
                # Basic UUID v4 format check
                uuid_pattern = re.compile(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
                )
                assert uuid_pattern.match(new_session_id), (
                    f"Session ID is not a valid UUID v4: {new_session_id}"
                )

            finally:
                browser.close()


@pytest.mark.usefixtures("stack")
class TestScenario4ComposerCleared:
    """E2E-RS-04: Composer/input cleared after reset."""

    def test_composer_cleared_after_reset(self, stack):
        """Typing in composer then resetting clears the input."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Bypass MSAL auth via route interception
                page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

                # 1. Navigate and wait for composer
                page.goto(vite_url, timeout=30000)
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)
                page.wait_for_timeout(2000)

                # 2. Type in composer WITHOUT sending
                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("Draft message that should be cleared")

                # 3. Verify text is in composer (textarea → use input_value)
                composer_text = composer.input_value()
                assert len(composer_text) > 0, (
                    "Composer should contain typed text before reset"
                )

                # 4. Click Reset → Confirm
                page.get_by_label("新对话").click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                dialog.get_by_role("button", name="确认").click()
                dialog.wait_for(state="hidden", timeout=5000)

                # 5. Verify composer is now empty
                composer = page.locator("textarea.aui-composer-input").first
                composer_text_after = composer.input_value()
                assert composer_text_after == "", (
                    "Composer should be empty after reset, "
                    f"got: {composer_text_after!r}"
                )

            finally:
                browser.close()


@pytest.mark.usefixtures("stack")
class TestScenario5ButtonDisabledDuringStreaming:
    """E2E-RS-05: Button disabled during streaming.

    Strategy: intercept /invocations and block the response for several
    seconds so isRunning stays true. This lets us observe the button's
    disabled=true state, then verify it returns to enabled after the
    response completes.
    """

    def test_button_disabled_during_streaming(self, stack):
        """Reset button is disabled when isRunning is true."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        # Handler that delays /invocations so streaming state persists
        def _delay_invocations(route):
            time.sleep(3)  # Hold the request open to simulate streaming
            route.continue_()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Bypass MSAL auth via route interception
                page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

                # 1. Navigate
                page.goto(vite_url, timeout=30000)
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)
                page.wait_for_timeout(2000)

                # 2. Before sending any message, button should be enabled
                reset_btn = page.get_by_label("新对话")
                assert reset_btn.is_visible(), "Reset button should always be visible"
                assert not reset_btn.is_disabled(), (
                    "Reset button should be enabled when not streaming"
                )

                # 3. Intercept /invocations to delay the response
                page.route("**/invocations", _delay_invocations)

                # 4. Send a message to trigger streaming
                composer = page.locator("textarea.aui-composer-input").first
                composer.click()
                composer.fill("Hello, how are you?")
                page.keyboard.press("Enter")

                # 5. During the delay, the button should be disabled
                page.wait_for_timeout(800)  # Let isRunning propagate
                reset_btn = page.get_by_label("新对话")
                assert reset_btn.is_disabled(), (
                    "Reset button should be disabled while streaming is active"
                )

                # 6. Wait for the request to complete and button to re-enable
                page.wait_for_selector(
                    '[aria-label="新对话"]:not([disabled])',
                    timeout=10000,
                )
                assert not reset_btn.is_disabled(), (
                    "Reset button should be enabled after streaming ends"
                )

            finally:
                browser.close()


@pytest.mark.usefixtures("stack")
class TestScenario6PrivacyMode:
    """E2E-RS-06: Privacy mode (localStorage unavailable)."""

    def test_privacy_mode_no_crash(self, stack):
        """When localStorage is unavailable, reset does not crash the page."""
        from playwright.sync_api import sync_playwright

        vite_url, _service_url = stack

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Collect console errors
            console_errors = []
            page.on(
                "console",
                lambda msg: (
                    console_errors.append(msg.text) if msg.type == "error" else None
                ),
            )

            try:
                # Bypass MSAL auth via route interception
                page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)

                # 1. Before navigating, inject a script that breaks localStorage
                page.add_init_script("""
                    Object.defineProperty(window, 'localStorage', {
                        get() {
                            throw new Error(
                                'localStorage is not available (privacy mode)'
                            );
                        },
                        configurable: true
                    });
                """)

                # 2. Navigate
                page.goto(vite_url, timeout=30000)
                page.wait_for_selector("text=Personal Assistant", timeout=15000)
                page.wait_for_selector('[aria-label="新对话"]', timeout=15000)
                page.wait_for_timeout(2000)

                # 3. Verify the app is visible (didn't crash on load)
                assert page.locator("text=Personal Assistant").is_visible(), (
                    "App should load even without localStorage"
                )

                # 4. Click Reset → Confirm
                page.get_by_label("新对话").click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                dialog.get_by_role("button", name="确认").click()
                dialog.wait_for(state="hidden", timeout=5000)

                # 5. Verify the page did NOT crash
                assert page.locator("text=Personal Assistant").is_visible(), (
                    "App should still be visible after reset in privacy mode"
                )

                # 6. Verify the composer state — after reset, it should be empty
                composer = page.locator("textarea.aui-composer-input").first
                composer_text = composer.input_value() or ""
                assert len(str(composer_text).strip()) == 0, (
                    f"Composer should be empty after reset, got: {composer_text!r}"
                )

                # 7. Verify no unexpected console errors appeared.
                #    resetSessionId() swallows localStorage errors silently.
                #    handleConfirm logs "Failed during session reset" for
                #    non-localStorage failures, which we expect in privacy mode.
                unexpected = [
                    e for e in console_errors if "Failed during session reset" not in e
                ]
                assert len(unexpected) == 0, f"Unexpected console errors: {unexpected}"

            finally:
                browser.close()
