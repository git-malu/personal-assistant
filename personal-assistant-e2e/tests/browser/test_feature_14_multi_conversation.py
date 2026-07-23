"""Browser E2E for Feature 14 multi-Conversation workflows.

The browser exercises the real React and assistant-ui runtime against a small
stateful HTTP double. Service persistence and authorization are covered by the
full-stack test and PostgreSQL integration suite.
"""

import json
import os
import socket
import subprocess
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest

from conftest import PROJECT_ROOT, terminate_process_tree

CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
pytestmark = [pytest.mark.browser, pytest.mark.feature, pytest.mark.slow]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ClientDevProcess:
    """Run Vite on a disposable port for one browser scenario."""

    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None

    def start(self, timeout: float = 60.0) -> None:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        self.process = subprocess.Popen(
            [
                npm,
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
            env={**os.environ, "BROWSER": "none"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    "Vite exited before browser E2E startup: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                if httpx.get(self.url, timeout=2.0).status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError("Vite did not become ready for browser E2E")

    def stop(self) -> None:
        if self.process is not None:
            terminate_process_tree(self.process)
        self.process = None


class ConversationHttpDouble:
    """Stateful Conversation API and SSE transport used by the browser."""

    def __init__(self):
        self.conversations: dict[str, dict] = {}
        self.invocation_headers: list[dict[str, str]] = []
        self.invocation_payloads: list[dict] = []
        self.deleted_message_count = 0
        self.sequence = 0

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _wire_conversation(self, conversation: dict) -> dict:
        return {
            key: conversation[key]
            for key in (
                "id",
                "title",
                "status",
                "created_at",
                "updated_at",
                "archived_at",
            )
        }

    def _json(self, route, status: int, body: dict | None = None) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body or {}),
        )

    def handle_conversations(self, route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        parts = [part for part in parsed.path.split("/") if part]
        method = request.method

        if parts == ["api", "conversations"]:
            if method == "GET":
                status = parse_qs(parsed.query).get("status", ["active"])[0]
                items = [
                    self._wire_conversation(item)
                    for item in sorted(
                        self.conversations.values(),
                        key=lambda item: item["updated_at"],
                        reverse=True,
                    )
                    if item["status"] == status
                ]
                self._json(route, 200, {"items": items, "next_cursor": None})
                return
            if method == "POST":
                payload = json.loads(request.post_data or "{}")
                now = self._now()
                conversation_id = str(uuid4())
                item = {
                    "id": conversation_id,
                    "title": payload.get("title") or "新对话",
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "archived_at": None,
                    "messages": [],
                }
                self.conversations[conversation_id] = item
                self._json(route, 201, self._wire_conversation(item))
                return

        if len(parts) >= 3 and parts[:2] == ["api", "conversations"]:
            conversation_id = parts[2]
            item = self.conversations.get(conversation_id)
            if item is None:
                self._json(route, 404, {"detail": "conversation not found"})
                return
            if len(parts) == 4 and parts[3] == "messages" and method == "GET":
                self._json(
                    route,
                    200,
                    {"items": item["messages"], "next_cursor": None},
                )
                return
            if len(parts) == 3 and method == "GET":
                self._json(route, 200, self._wire_conversation(item))
                return
            if len(parts) == 3 and method == "PATCH":
                payload = json.loads(request.post_data or "{}")
                if "title" in payload:
                    item["title"] = payload["title"]
                if "status" in payload:
                    item["status"] = payload["status"]
                    item["archived_at"] = (
                        self._now() if payload["status"] == "archived" else None
                    )
                item["updated_at"] = self._now()
                self._json(route, 200, self._wire_conversation(item))
                return
            if len(parts) == 3 and method == "DELETE":
                self.deleted_message_count += len(item["messages"])
                del self.conversations[conversation_id]
                route.fulfill(status=204, body="")
                return

        self._json(route, 405, {"detail": "method not allowed"})

    def handle_invocation(self, route) -> None:
        request = route.request
        payload = json.loads(request.post_data or "{}")
        self.invocation_payloads.append(payload)
        conversation = self.conversations.get(payload["conversation_id"])
        if conversation is None:
            self._json(route, 404, {"detail": "conversation not found"})
            return
        self.invocation_headers.append(dict(request.headers))

        self.sequence += 1
        user_id = str(uuid4())
        now = self._now()
        conversation["messages"].append(
            {
                "sequence": self.sequence,
                "id": user_id,
                "role": "user",
                "content": {
                    "version": 1,
                    "parts": [{"type": "text", "text": payload["message"]}],
                },
                "client_message_id": payload["client_message_id"],
                "reply_to_message_id": None,
                "created_at": now,
            }
        )
        self.sequence += 1
        answer = f"Answer: {payload['message']}"
        conversation["messages"].append(
            {
                "sequence": self.sequence,
                "id": str(uuid4()),
                "role": "assistant",
                "content": {
                    "version": 1,
                    "parts": [{"type": "text", "text": answer}],
                },
                "client_message_id": None,
                "reply_to_message_id": user_id,
                "created_at": self._now(),
            }
        )
        conversation["updated_at"] = self._now()
        body = (
            f"data: {json.dumps({'token': answer, 'done': False})}\n\n"
            f"data: {json.dumps({'token': '', 'done': True})}\n\n"
        )
        route.fulfill(status=200, content_type="text/event-stream", body=body)


@pytest.fixture
def vite_url():
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip("Client node_modules is required for browser E2E")
    process = ClientDevProcess(_find_free_port())
    process.start()
    try:
        yield process.url
    finally:
        process.stop()


def _send(page, text: str, backend: ConversationHttpDouble, errors: list[str]) -> None:
    composer = page.get_by_label("Message input")
    composer.fill(text)
    page.get_by_label("Send message").click()
    try:
        page.get_by_text(f"Answer: {text}", exact=True).wait_for(timeout=15_000)
    except Exception as error:
        raise AssertionError(
            "Browser send did not complete. "
            f"payloads={backend.invocation_payloads!r} "
            f"errors={errors!r} body={page.locator('body').inner_text()[-1000:]!r}"
        ) from error


def test_create_send_switch_refresh_and_delete(vite_url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")

    backend = ConversationHttpDouble()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f"Playwright Chromium is unavailable: {error}")

        page = browser.new_page(viewport={"width": 1280, "height": 800})
        browser_errors: list[str] = []
        page.on(
            "console",
            lambda message: (
                browser_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.route("**/api/conversations**", backend.handle_conversations)
        page.route("**/invocations", backend.handle_invocation)
        try:
            page.goto(vite_url, wait_until="networkidle", timeout=30_000)
            page.get_by_label("Message input").wait_for(timeout=15_000)

            alpha = "Plan alpha follow-up"
            beta = "Summarize beta notes"
            _send(page, alpha, backend, browser_errors)
            page.get_by_role("button", name=alpha, exact=True).wait_for()

            page.get_by_label("New conversation").click()
            _send(page, beta, backend, browser_errors)
            page.get_by_role("button", name=beta, exact=True).wait_for()

            page.get_by_role("button", name=alpha, exact=True).click()
            page.get_by_text(f"Answer: {alpha}", exact=True).wait_for()
            assert page.get_by_text(f"Answer: {beta}", exact=True).count() == 0

            page.reload(wait_until="networkidle")
            page.get_by_role("button", name=alpha, exact=True).click()
            page.get_by_text(f"Answer: {alpha}", exact=True).wait_for()

            title_button = page.get_by_role("button", name=alpha, exact=True)
            title_button.locator("..").get_by_label("Conversation actions").click()
            page.get_by_role("menuitem", name="Delete").click()
            dialog = page.get_by_role("dialog", name="Delete conversation?")
            dialog.get_by_role("button", name="Delete", exact=True).click()
            title_button.wait_for(state="detached", timeout=10_000)

            page.reload(wait_until="networkidle")
            assert page.get_by_role("button", name=alpha, exact=True).count() == 0
            page.get_by_role("button", name=beta, exact=True).click()
            page.get_by_text(f"Answer: {beta}", exact=True).wait_for()

            assert backend.deleted_message_count == 2
            assert len(backend.invocation_headers) == 2
            for headers in backend.invocation_headers:
                assert "x-hw-agentarts-session-id" not in headers
                assert "x-hw-agentgateway-user-id" not in headers
        finally:
            page.close()
            browser.close()


@pytest.mark.regression
def test_bug_25_first_conversation_survives_delayed_initial_list(vite_url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")

    backend = ConversationHttpDouble()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f"Playwright Chromium is unavailable: {error}")

        page = browser.new_page(viewport={"width": 1280, "height": 800})
        browser_errors: list[str] = []
        page.on(
            "console",
            lambda message: (
                browser_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.add_init_script(
            script="""
                (() => {
                  const originalFetch = window.fetch.bind(window);
                  let releaseLists;
                  const listGate = new Promise((resolve) => {
                    releaseLists = resolve;
                  });
                  window.__bug25PendingLists = 0;
                  window.__releaseBug25Lists = () => releaseLists();
                  window.fetch = async (input, init) => {
                    const request = input instanceof Request ? input : null;
                    const method = (
                      init?.method ?? request?.method ?? "GET"
                    ).toUpperCase();
                    const rawUrl = typeof input === "string" ? input : input.url;
                    const response = await originalFetch(input, init);
                    const path = new URL(rawUrl, window.location.href).pathname;
                    if (method === "GET" && path === "/api/conversations") {
                      window.__bug25PendingLists += 1;
                      await listGate;
                    }
                    return response;
                  };
                })();
            """
        )
        page.route("**/api/conversations**", backend.handle_conversations)
        page.route("**/invocations", backend.handle_invocation)
        try:
            page.goto(vite_url, wait_until="domcontentloaded", timeout=30_000)
            page.get_by_label("Message input").wait_for(timeout=15_000)
            page.wait_for_function("window.__bug25PendingLists === 2")

            message = "First conversation remains visible"
            page.get_by_label("Message input").fill(message)
            page.get_by_label("Send message").click()

            assert backend.conversations == {}
            assert backend.invocation_payloads == []

            page.evaluate("window.__releaseBug25Lists()")
            page.get_by_text(f"Answer: {message}", exact=True).wait_for(timeout=15_000)
            page.get_by_role("button", name=message, exact=True).wait_for()

            assert len(backend.conversations) == 1
            assert len(backend.invocation_payloads) == 1
            assert page.get_by_role("button", name=message, exact=True).count() == 1
            assert browser_errors == []
        finally:
            page.close()
            browser.close()
