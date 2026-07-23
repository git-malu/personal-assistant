"""Feature 14 full-stack boundary: Pages Functions, Service, and PostgreSQL."""

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest

from conftest import (
    PROJECT_ROOT,
    ServiceProcess,
    _get_uv_path,
    terminate_process_tree,
)

CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
SCHEMA_SCRIPT = (
    PROJECT_ROOT / "personal-assistant-e2e" / "scripts" / "postgres_schema.py"
)
RUNTIME_COOKIE_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
pytestmark = [pytest.mark.full_stack, pytest.mark.feature, pytest.mark.slow]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _node_command() -> str:
    return shutil.which("node.exe") or shutil.which("node") or "node"


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _gateway_jwt(subject: str) -> str:
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": subject}, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    return f"header.{encoded}.signature"


def _set_cookie_value(response: httpx.Response, name: str) -> str | None:
    prefix = f"{name}="
    for value in response.headers.get_list("set-cookie"):
        if value.startswith(prefix):
            return value[len(prefix) :].split(";", maxsplit=1)[0]
    return None


def _manage_schema(action: str, schema: str, env: dict[str, str]) -> None:
    result = subprocess.run(
        [_get_uv_path(), "run", "python", str(SCHEMA_SCRIPT), action, schema],
        cwd=str(SERVICE_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not {action} E2E schema {schema}:\n"
            f"{result.stdout[-500:]}\n{result.stderr[-500:]}"
        )


class PagesDevProcess:
    """Run the production Pages Functions topology on a disposable port."""

    def __init__(self, *, port: int, service_url: str):
        self.port = port
        self.service_url = service_url
        self.url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None

    def start(self, timeout: float = 60.0) -> None:
        build = subprocess.run(
            [_npm_command(), "run", "build"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if build.returncode != 0:
            raise RuntimeError(
                "Client build failed before Pages E2E:\n"
                f"{build.stdout[-1000:]}\n{build.stderr[-1000:]}"
            )

        wrangler = CLIENT_DIR / "node_modules" / "wrangler" / "bin" / "wrangler.js"
        self.process = subprocess.Popen(
            [
                _node_command(),
                str(wrangler),
                "pages",
                "dev",
                "dist",
                "--ip",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--binding",
                "PA_ENV=local",
                "--binding",
                f"AGENTARTS_INVOCATIONS_URL={self.service_url}",
                "--binding",
                (
                    "AGENTARTS_OAUTH_CALLBACK_URL="
                    f"{self.service_url}/auth/oauth2/callback/m365-calendar"
                ),
            ],
            cwd=str(CLIENT_DIR),
            env={**os.environ, "BROWSER": "none"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    "Pages dev exited before E2E startup:\n"
                    f"{stdout.decode(errors='replace')[-500:]}\n"
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                if httpx.get(self.url, timeout=2.0).status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError("Pages dev did not become ready for full-stack E2E")

    def stop(self) -> None:
        if self.process is not None:
            terminate_process_tree(self.process)
        self.process = None


class ViteDevProcess:
    """Run the Dev Mode UI while proxying API calls through Pages Functions."""

    def __init__(self, *, port: int, proxy_target: str):
        self.port = port
        self.proxy_target = proxy_target
        self.url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None

    def start(self, timeout: float = 60.0) -> None:
        self.process = subprocess.Popen(
            [
                _npm_command(),
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--strictPort",
            ],
            cwd=str(CLIENT_DIR),
            env={
                **os.environ,
                "BROWSER": "none",
                "PA_SERVICE_PROXY_TARGET": self.proxy_target,
                "VITE_ENTRA_CLIENT_ID": "",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    "Vite exited before Bug 26 E2E startup:\n"
                    f"{stdout.decode(errors='replace')[-500:]}\n"
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                if httpx.get(self.url, timeout=2.0).status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError("Vite did not become ready for Bug 26 E2E")

    def stop(self) -> None:
        if self.process is not None:
            terminate_process_tree(self.process)
        self.process = None


@pytest.fixture
def pages_stack():
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for Feature 14 full-stack E2E")
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip("Client node_modules is required for Feature 14 full-stack E2E")

    schema = f"pa_e2e_{uuid4().hex}"
    base_env = {**os.environ, "TEST_POSTGRES_DSN": dsn}
    base_env.pop("PGOPTIONS", None)
    _manage_schema("create", schema, base_env)
    try:
        env = {
            **base_env,
            "POSTGRES_DSN": dsn,
            "SQLITE_DB_PATH": "",
            "PGOPTIONS": f"-c search_path={schema}",
            "PA_E2E_ASGI_APP": "support.feature14_app:app",
            "PA_E2E_AGENT_DELAY_SECONDS": "0.5",
        }
        migration = subprocess.run(
            [_get_uv_path(), "run", "alembic", "upgrade", "head"],
            cwd=str(SERVICE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if migration.returncode != 0:
            raise RuntimeError(
                "Feature 14 migration failed before E2E:\n"
                f"{migration.stdout[-1000:]}\n{migration.stderr[-1000:]}"
            )

        service = ServiceProcess(port=_find_free_port())
        pages = PagesDevProcess(port=_find_free_port(), service_url=service.url)
        try:
            service.start(env=env)
            pages.start()
            yield pages.url
        finally:
            pages.stop()
            service.stop()
    finally:
        _manage_schema("drop", schema, base_env)


def _client(base_url: str, subject: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {_gateway_jwt(subject)}",
            "X-HW-AgentGateway-User-Id": "forged-browser-user",
            "X-HW-AgentArts-Session-Id": "forged-browser-session",
        },
        timeout=20.0,
    )


def _abort_invocation(
    *,
    base_url: str,
    authorization: str,
    runtime_session: str,
    payload: dict[str, object],
) -> None:
    script = """
const controller = new AbortController();
const response = await fetch(`${process.env.PA_E2E_BASE_URL}/invocations`, {
  method: "POST",
  headers: {
    Accept: "text/event-stream",
    Authorization: process.env.PA_E2E_AUTHORIZATION,
    Cookie: `pa_runtime_session=${process.env.PA_E2E_RUNTIME_SESSION}`,
    "Content-Type": "application/json",
  },
  body: process.env.PA_E2E_PAYLOAD,
  signal: controller.signal,
});
if (response.status !== 200) {
  throw new Error(`Invocation returned ${response.status}`);
}
controller.abort();
try {
  await response.text();
} catch (error) {
  if (error?.name !== "AbortError") throw error;
}
const invocation = JSON.parse(process.env.PA_E2E_PAYLOAD);
const cancelUrl = new URL(
  `/api/conversations/${invocation.conversation_id}/invocations/${invocation.client_message_id}/cancel`,
  process.env.PA_E2E_BASE_URL,
);
const cancelled = await fetch(cancelUrl, {
  method: "POST",
  headers: {
    Accept: "application/json",
    Authorization: process.env.PA_E2E_AUTHORIZATION,
    Cookie: `pa_runtime_session=${process.env.PA_E2E_RUNTIME_SESSION}`,
  },
});
if (cancelled.status !== 204) {
  throw new Error(`Cancellation returned ${cancelled.status}`);
}
"""
    result = subprocess.run(
        [_node_command(), "--input-type=module", "--eval", script],
        env={
            **os.environ,
            "PA_E2E_BASE_URL": base_url,
            "PA_E2E_AUTHORIZATION": authorization,
            "PA_E2E_RUNTIME_SESSION": runtime_session,
            "PA_E2E_PAYLOAD": json.dumps(payload),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_cookie_multi_browser_ownership_delete_and_oauth_snapshot(
    pages_stack,
):
    user_subject = f"feature-14-{uuid4()}"
    stranger_subject = f"feature-14-stranger-{uuid4()}"
    conversation_id: str | None = None
    with (
        _client(pages_stack, user_subject) as first,
        _client(pages_stack, user_subject) as second,
        _client(pages_stack, stranger_subject) as stranger,
    ):
        first_list = first.get("/api/conversations?status=active&limit=20")
        assert first_list.status_code == 200
        first_runtime = first.cookies.get("pa_runtime_session")
        assert first_runtime and RUNTIME_COOKIE_PATTERN.fullmatch(first_runtime)
        assert "HttpOnly" in first_list.headers.get("set-cookie", "")
        assert "SameSite=Lax" in first_list.headers.get("set-cookie", "")
        assert "Secure" not in first_list.headers.get("set-cookie", "")
        assert first_runtime != "forged-browser-session"

        created = first.post(
            "/api/conversations",
            json={"title": "Feature 14 E2E conversation"},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        second_list = second.get("/api/conversations?status=active&limit=20")
        assert second_list.status_code == 200
        second_runtime = second.cookies.get("pa_runtime_session")
        assert second_runtime and RUNTIME_COOKIE_PATTERN.fullmatch(second_runtime)
        assert second_runtime != first_runtime
        assert conversation_id in {item["id"] for item in second_list.json()["items"]}

        denied = stranger.get(f"/api/conversations/{conversation_id}")
        assert denied.status_code == 404
        denied_patch = stranger.patch(
            f"/api/conversations/{conversation_id}",
            json={"title": "stolen"},
        )
        assert denied_patch.status_code == 404
        still_owned = first.get(f"/api/conversations/{conversation_id}")
        assert still_owned.status_code == 200
        assert still_owned.json()["title"] == "Feature 14 E2E conversation"

        stream_created = first.post(
            "/api/conversations",
            json={"title": "Feature 14 SSE E2E"},
        )
        assert stream_created.status_code == 201
        stream_conversation_id = stream_created.json()["id"]
        streamed = first.post(
            "/invocations",
            json={
                "conversation_id": stream_conversation_id,
                "client_message_id": str(uuid4()),
                "message": "streamed message",
                "stream": True,
            },
            headers={"Accept": "text/event-stream"},
        )
        assert streamed.status_code == 200
        assert "text/event-stream" in streamed.headers["content-type"]
        stream_events = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        assert stream_events[-1] == {"token": "", "done": True}
        stream_history = first.get(
            f"/api/conversations/{stream_conversation_id}/messages?limit=100"
        )
        assert [item["role"] for item in stream_history.json()["items"]] == [
            "user",
            "assistant",
        ]
        assert (
            first.delete(f"/api/conversations/{stream_conversation_id}").status_code
            == 204
        )
        assert (
            first.get(
                f"/api/conversations/{stream_conversation_id}/messages"
            ).status_code
            == 404
        )

        invocation = first.post(
            "/invocations",
            json={
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "",
                "stream": True,
            },
            headers={"Accept": "text/event-stream"},
        )
        assert invocation.status_code == 400
        callback_session = _set_cookie_value(invocation, "pa_oauth2_callback_session")
        callback_auth = _set_cookie_value(invocation, "pa_oauth2_callback_auth")
        assert callback_session == first_runtime
        assert callback_auth == quote(first.headers["Authorization"], safe="")

        rotated_runtime = str(uuid4())
        first.headers["Cookie"] = f"pa_runtime_session={rotated_runtime}"
        rotated_list = first.get("/api/conversations?status=active&limit=20")
        assert rotated_list.status_code == 200
        assert _set_cookie_value(rotated_list, "pa_runtime_session") is None
        assert callback_session != rotated_runtime

        first.headers["Cookie"] = (
            f"pa_runtime_session={rotated_runtime}; "
            f"pa_oauth2_callback_session={callback_session}; "
            f"pa_oauth2_callback_auth={callback_auth}"
        )
        callback = first.get("/auth/callback/m365-calendar?state=e2e-capture")
        assert callback.status_code == 200
        assert callback.json() == {
            "authorization": first.headers["Authorization"],
            "runtime_session": first_runtime,
        }

        invalid_cookie = _client(pages_stack, user_subject)
        try:
            invalid_cookie.headers["Cookie"] = "pa_runtime_session=not-a-uuid"
            rotated_response = invalid_cookie.get(
                "/api/conversations?status=active&limit=20"
            )
            replacement = _set_cookie_value(rotated_response, "pa_runtime_session")
            assert rotated_response.status_code == 200
            assert replacement and RUNTIME_COOKIE_PATTERN.fullmatch(replacement)
        finally:
            invalid_cookie.close()

        payloads = [
            {
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "first concurrent message",
                "stream": False,
            },
            {
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "second concurrent message",
                "stream": False,
            },
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(first.post, "/invocations", json=payloads[0]),
                executor.submit(second.post, "/invocations", json=payloads[1]),
            ]
            concurrent = [future.result(timeout=20) for future in futures]
        assert sorted(response.status_code for response in concurrent) == [200, 409]
        busy = next(response for response in concurrent if response.status_code == 409)
        assert busy.json() == {
            "code": "conversation_busy",
            "detail": "conversation is busy",
        }

        history = first.get(f"/api/conversations/{conversation_id}/messages?limit=100")
        assert history.status_code == 200
        assert [item["role"] for item in history.json()["items"]] == [
            "user",
            "assistant",
        ]

        deleted = first.delete(f"/api/conversations/{conversation_id}")
        assert deleted.status_code == 204
        assert first.get(f"/api/conversations/{conversation_id}").status_code == 404
        assert (
            first.get(f"/api/conversations/{conversation_id}/messages").status_code
            == 404
        )
        after_delete = second.get("/api/conversations?status=active&limit=20")
        assert conversation_id not in {
            item["id"] for item in after_delete.json()["items"]
        }
        conversation_id = None

        logout = first.post("/auth/logout")
        assert logout.status_code == 204
        logout_cookies = logout.headers.get_list("set-cookie")
        assert any(
            value.startswith("pa_runtime_session=; Max-Age=0")
            for value in logout_cookies
        )
        assert any(
            value.startswith("pa_oauth2_callback_session=; Max-Age=0")
            for value in logout_cookies
        )

    if conversation_id is not None:
        with _client(pages_stack, user_subject) as cleanup:
            cleanup.delete(f"/api/conversations/{conversation_id}")


@pytest.mark.regression
def test_bug_23_cancelled_stream_allows_next_invocation(pages_stack):
    user_subject = f"bug-23-{uuid4()}"
    with _client(pages_stack, user_subject) as client:
        created = client.post(
            "/api/conversations",
            json={"title": "Bug 23 cancellation regression"},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        runtime_session = client.cookies.get("pa_runtime_session")
        assert runtime_session
        _abort_invocation(
            base_url=pages_stack,
            authorization=client.headers["Authorization"],
            runtime_session=runtime_session,
            payload={
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "cancel this response",
                "stream": True,
            },
        )

        retried = client.post(
            "/invocations",
            json={
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "continue after cancellation",
                "stream": False,
            },
        )

        assert retried.status_code == 200
        assert retried.json() == {"response": "Echo: continue after cancellation"}


@pytest.mark.browser
@pytest.mark.regression
def test_bug_26_cancel_failure_shows_retry_before_next_invocation(pages_stack):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.getenv("CI"):
            raise
        pytest.skip("playwright is not installed")

    cancel_attempts = 0

    def intercept_cancellation(route) -> None:
        nonlocal cancel_attempts
        cancel_attempts += 1
        if cancel_attempts <= 2:
            route.fulfill(
                status=404,
                content_type="application/json",
                body=json.dumps({"detail": "Not Found"}),
            )
            return
        route.continue_()

    vite = ViteDevProcess(port=_find_free_port(), proxy_target=pages_stack)
    vite.start()
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as error:
                if os.getenv("CI"):
                    raise
                pytest.skip(f"Playwright Chromium is unavailable: {error}")

            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.route(
                "**/api/conversations/*/invocations/*/cancel",
                intercept_cancellation,
            )
            try:
                page.goto(vite.url, wait_until="networkidle", timeout=30_000)
                composer = page.get_by_label("Message input")
                composer.wait_for(timeout=15_000)
                composer.fill("cancel this response")
                page.get_by_label("Send message").click()

                stop = page.get_by_label("Stop generating")
                stop.wait_for(timeout=10_000)
                stop.click()

                retry = page.get_by_label("Retry stop")
                retry.wait_for(timeout=10_000)
                assert cancel_attempts == 2
                assert page.get_by_label("Send message").count() == 0
                assert page.get_by_text("Not Found", exact=True).count() == 0

                composer.fill("continue after cancellation")
                composer.press("Enter")
                assert composer.input_value() == "continue after cancellation"

                retry.click()
                page.get_by_label("Send message").wait_for(timeout=10_000)
                assert cancel_attempts == 3
                assert composer.input_value() == "continue after cancellation"

                page.get_by_label("Send message").click()
                page.get_by_text(
                    "Echo: continue after cancellation",
                    exact=True,
                ).wait_for(timeout=15_000)
            finally:
                page.close()
                browser.close()
    finally:
        vite.stop()
