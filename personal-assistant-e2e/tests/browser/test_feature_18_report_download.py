"""Browser E2E for the Feature 18 Markdown report download card."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from test_feature_14_multi_conversation import ConversationHttpDouble

from conftest import PROJECT_ROOT, terminate_process_tree

CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
pytestmark = [pytest.mark.browser, pytest.mark.feature, pytest.mark.slow]

REPORT_CONTENT = """# 日报

- 时间范围：2024-02-14T00:00:00+08:00 至 2024-02-14T23:59:59+08:00

## GitHub 工程活动

- 2024-02-14 | commit：Feature 18 download

## 邮件

- 本时间范围内没有可用证据。

## 日历

- 本时间范围内没有可用证据。

## 数据覆盖与提醒

所有已选择数据源均完成本次采集。
"""

ASSISTANT_DISPLAYED_MARKDOWN = """# 报告已生成

完整报告请使用下方下载按钮保存。
"""


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ClientDevProcess:
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
                    "Vite exited before Feature 18 browser E2E startup: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                if httpx.get(self.url, timeout=2.0).status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError("Vite did not become ready for Feature 18 browser E2E")

    def stop(self) -> None:
        if self.process is not None:
            terminate_process_tree(self.process)
        self.process = None


@pytest.fixture
def vite_url():
    configured_url = os.getenv("PA_E2E_CLIENT_BASE_URL", "").rstrip("/")
    if configured_url:
        yield configured_url
        return
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip("Client node_modules is required for browser E2E")
    process = ClientDevProcess(_find_free_port())
    process.start()
    try:
        yield process.url
    finally:
        process.stop()


INITIAL_REPORT_EVENTS = (
    {
        "system_message": "请完成 GitHub 授权",
        "auth_required": True,
        "auth_url": "https://auth.example.com/github",
        "provider": "github-provider",
    },
    {
        "system_message": "GitHub 授权已完成",
        "auth_complete": True,
        "provider": "github-provider",
    },
    {
        "system_message": "请完成邮件授权",
        "auth_required": True,
        "auth_url": "https://auth.example.com/email",
        "provider": "m365-email-provider",
    },
    {
        "system_message": "邮件授权已完成",
        "auth_complete": True,
        "provider": "m365-email-provider",
    },
    {
        "system_message": "请完成日历授权",
        "auth_required": True,
        "auth_url": "https://auth.example.com/calendar",
        "oauth2_state": "feature-18-calendar-state",
        "provider": "m365-calendar-provider",
    },
    {
        "system_message": "日历授权已完成",
        "auth_complete": True,
        "oauth2_state": "feature-18-calendar-state",
        "provider": "m365-calendar-provider",
    },
    {
        "type": "report_progress",
        "report_progress": True,
        "sequence": 1,
        "source": "github",
        "stage": "activity_detail",
        "status": "running",
        "current": 18,
        "total": 37,
        "discovered": 37,
        "system_message": "Feature 18 progress sentinel",
    },
    {
        "type": "report_progress",
        "report_progress": True,
        "sequence": 2,
        "source": "email",
        "stage": "email_collection",
        "status": "complete",
        "current": 2,
        "total": 2,
        "discovered": 4,
    },
    {
        "type": "report_progress",
        "report_progress": True,
        "sequence": 3,
        "source": "calendar",
        "stage": "calendar_collection",
        "status": "running",
        "current": 0,
        "total": 1,
    },
)

FINAL_REPORT_EVENTS = (
    {
        "type": "report_progress",
        "report_progress": True,
        "sequence": 4,
        "stage": "rendering",
        "status": "complete",
    },
    {
        "type": "report_ready",
        "report_ready": True,
        "report_format": "markdown",
        "report_filename": "日报-2024-02-14.md",
        "report_content": REPORT_CONTENT,
        "report_type": "daily",
    },
    {"token": ASSISTANT_DISPLAYED_MARKDOWN, "done": False},
    {"token": "", "done": True},
)


def _sse_body(events: tuple[dict[str, object], ...]) -> str:
    return "".join(
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events
    )


def _report_stream_init_script() -> str:
    initial_body = json.dumps(_sse_body(INITIAL_REPORT_EVENTS), ensure_ascii=False)
    final_body = json.dumps(_sse_body(FINAL_REPORT_EVENTS), ensure_ascii=False)
    return f"""
(() => {{
  const originalFetch = window.fetch.bind(window);
  const initialBody = {initial_body};
  const finalBody = {final_body};
  let releaseReport = null;
  window.__feature18ReleaseReport = () => releaseReport?.();
  window.fetch = async (...args) => {{
    const input = args[0];
    const init = args[1] ?? {{}};
    const rawUrl = typeof input === "string" ? input : input.url;
    const method = String(init.method ?? input.method ?? "GET").toUpperCase();
    const path = new URL(rawUrl, window.location.href).pathname;
    if (path === "/invocations" && method === "POST") {{
      const encoder = new TextEncoder();
      return new Response(new ReadableStream({{
        start(controller) {{
          controller.enqueue(encoder.encode(initialBody));
          releaseReport = () => {{
            controller.enqueue(encoder.encode(finalBody));
            controller.close();
            releaseReport = null;
          }};
        }},
      }}), {{
        status: 200,
        headers: {{ "Content-Type": "text/event-stream" }},
      }});
    }}
    return originalFetch(...args);
  }};
}})();
"""


def _handle_auth_route(route) -> None:
    response = route.fetch()
    body = response.text()
    body = re.sub(
        r"export async function acquireIdTokenSilently\(\): "
        r"Promise<string \| null> \{.*?\n\}\n\n"
        r"export async function clearInboundAuthSession",
        "export async function acquireIdTokenSilently(): Promise<string | null> {\n"
        '  return "feature18-browser-token";\n'
        "}\n\nexport async function clearInboundAuthSession",
        body,
        flags=re.S,
    )
    route.fulfill(status=response.status, headers=dict(response.headers), body=body)


def _handle_app_route(route) -> None:
    response = route.fetch()
    body = re.sub(
        r"const isAuthenticated = useIsAuthenticated\(\);",
        "const isAuthenticated = true; // Feature 18 browser auth double",
        response.text(),
        count=1,
    )
    body = re.sub(
        r"const canShowChat = [^;]+;",
        "const canShowChat = true; // Feature 18 browser auth double",
        body,
        count=1,
    )
    route.fulfill(status=response.status, headers=dict(response.headers), body=body)


@pytest.mark.parametrize(
    "viewport",
    (
        {"width": 1280, "height": 900},
        {"width": 390, "height": 844},
    ),
    ids=("desktop", "mobile"),
)
def test_feature_18_report_download_card_and_markdown_file(vite_url, viewport):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")

    backend = ConversationHttpDouble()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        except Exception as chrome_error:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as bundled_error:
                pytest.skip(
                    "Google Chrome and bundled Chromium are unavailable: "
                    f"chrome={chrome_error}; bundled={bundled_error}"
                )

        page = browser.new_page(viewport=viewport)
        page.add_init_script(
            "Object.defineProperty(window, 'showSaveFilePicker', "
            "{ configurable: true, value: undefined });"
        )
        page.add_init_script(_report_stream_init_script())
        page.route(lambda url: "/src/lib/auth.ts" in url, _handle_auth_route)
        page.route(lambda url: "/src/App.tsx" in url, _handle_app_route)
        page.route("**/api/conversations**", backend.handle_conversations)
        try:
            page.goto(vite_url, wait_until="networkidle", timeout=30_000)
            try:
                page.get_by_label("Message input").wait_for(timeout=15_000)
            except Exception as error:
                raise AssertionError(
                    f"Chat UI did not load at {page.url}: "
                    f"{page.locator('body').inner_text()[-1000:]!r}"
                ) from error
            page.get_by_label("Message input").fill("请生成 2024-02-14 的日报")
            page.get_by_label("Send message").click()

            progress_panel = page.locator('[data-slot="report-progress-panel"]')
            progress_panel.wait_for(timeout=15_000)
            auth_cards = page.locator('[data-slot="auth-card"]')
            assert auth_cards.count() == 3
            assert [
                auth_cards.nth(index).get_attribute("data-provider")
                for index in range(3)
            ] == [
                "github-provider",
                "m365-email-provider",
                "m365-calendar-provider",
            ]
            assert auth_cards.get_by_text("授权完成", exact=True).count() == 3

            progress_rows = progress_panel.locator('[data-slot="report-progress-row"]')
            assert [
                progress_rows.nth(index).get_attribute("data-source")
                for index in range(progress_rows.count())
            ] == ["github", "email", "calendar"]
            assert progress_panel.get_by_text("18 / 37", exact=True).is_visible()
            assert page.get_by_text("Feature 18 progress sentinel").count() == 0
            assert page.locator('[data-slot="report-download-card"]').count() == 0

            auth_boxes = [auth_cards.nth(index).bounding_box() for index in range(3)]
            progress_box = progress_panel.bounding_box()
            assert all(box is not None for box in auth_boxes)
            assert progress_box is not None
            for current_box, next_box in zip(auth_boxes, auth_boxes[1:], strict=False):
                assert current_box is not None and next_box is not None
                assert current_box["y"] + current_box["height"] <= next_box["y"]
            last_auth_box = auth_boxes[-1]
            assert last_auth_box is not None
            assert last_auth_box["y"] + last_auth_box["height"] <= progress_box["y"]
            assert page.evaluate(
                "document.documentElement.scrollWidth <= "
                "document.documentElement.clientWidth + 1"
            )

            page.evaluate("window.__feature18ReleaseReport()")
            heading = page.get_by_role("heading", name="报告已生成", exact=True)
            heading.wait_for(timeout=15_000)
            assert progress_panel.count() == 0

            card = page.locator('[data-slot="report-download-card"]')
            card.wait_for(timeout=15_000)
            assert card.get_by_text("Markdown 报告已生成", exact=True).is_visible()
            button = card.get_by_role("button", name="下载 Markdown 报告")
            assert button.count() == 1

            heading_box = heading.bounding_box()
            card_box = card.bounding_box()
            assert heading_box is not None and card_box is not None
            auth_boxes = [auth_cards.nth(index).bounding_box() for index in range(3)]
            assert all(box is not None for box in auth_boxes)
            for current_box, next_box in zip(auth_boxes, auth_boxes[1:], strict=False):
                assert current_box is not None and next_box is not None
                assert current_box["y"] + current_box["height"] <= next_box["y"]
            last_auth_box = auth_boxes[-1]
            assert last_auth_box is not None
            assert last_auth_box["y"] + last_auth_box["height"] <= heading_box["y"]
            assert card_box["y"] > heading_box["y"]

            with page.expect_download(timeout=15_000) as download_info:
                button.click()
            download = download_info.value
            assert download.suggested_filename == "日报-2024-02-14.md"
            download_path = download.path()
            assert download_path is not None
            downloaded_content = Path(download_path).read_text(encoding="utf-8")
            assert REPORT_CONTENT != ASSISTANT_DISPLAYED_MARKDOWN
            assert downloaded_content == REPORT_CONTENT
        finally:
            page.close()
            browser.close()
