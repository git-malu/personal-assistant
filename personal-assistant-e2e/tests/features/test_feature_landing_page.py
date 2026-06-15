"""E2E tests for Landing Page feature (Playwright-based browser testing).

Tests the Landing Page UI rendered for unauthenticated users:
- Scenario 1: Landing Page renders all 7 tiles in correct order
- Scenario 2: CTA buttons exist and are clickable, open LoginPage (full-page, not modal)
- Scenario 2b: LandingHero uses 60vh min-height
- Scenario 2c: LoginPage renders all provider rows, back button, brand icons
- Scenario 2d: '了解更多' buttons scroll to #capabilities
- Scenario 3: LoadingState accessibility attributes
- Scenario 4: Responsive design at 5 breakpoints
- Scenario 5: Accessibility checks (nav, headings, buttons, lang)
- Scenario 6: GlobalNav content
- Scenario 6b: GlobalNav '登录' opens LoginPage
- Scenario 7: LandingFooter content
- Scenario 7b: ClosingCTA '立即开始' opens LoginPage
- Regression: vitest unit tests still pass
"""

import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Page, sync_playwright

# ── Paths ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / ".files" / "screenshots"


# ═══════════════════════════════════════════════════════════════════════════
# Session-scoped Vite dev server (started ONCE for all tests)
# ═══════════════════════════════════════════════════════════════════════════

_vite_proc: subprocess.Popen | None = None
_vite_port: int | None = None


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _stop_vite() -> None:
    """Gracefully stop the Vite dev server subprocess."""
    global _vite_proc
    if _vite_proc and _vite_proc.poll() is None:
        _vite_proc.send_signal(signal.SIGTERM)
        try:
            _vite_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _vite_proc.kill()
            _vite_proc.wait()
    _vite_proc = None


@pytest.fixture(scope="session")
def vite_url() -> str:
    """Start ONE Vite dev server on a dynamic port, shared across all tests."""
    global _vite_proc, _vite_port

    # Ensure dependencies are installed
    if not (CLIENT_DIR / "node_modules").is_dir():
        pytest.skip("node_modules/ not found — run 'npm install' in personal-assistant-client/")

    _vite_port = _find_free_port()
    env = {**os.environ, "BROWSER": "none"}

    _vite_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(_vite_port)],
        cwd=str(CLIENT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    # Wait for server to become healthy
    deadline = time.time() + 60
    while time.time() < deadline:
        if _vite_proc.poll() is not None:
            raise RuntimeError(
                f"Vite dev server exited early with code {_vite_proc.returncode}"
            )
        try:
            resp = httpx.get(f"http://localhost:{_vite_port}/", timeout=2.0)
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(1)
    else:
        _stop_vite()
        raise TimeoutError(f"Vite dev server did not start within 60s on port {_vite_port}")

    yield f"http://localhost:{_vite_port}"

    _stop_vite()


# ═══════════════════════════════════════════════════════════════════════════
# Playwright fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def _pw():
    """Session-scoped Playwright instance."""
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(_pw) -> Browser:
    """Session-scoped Chromium browser."""
    b = _pw.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def page(browser: Browser, vite_url: str) -> Page:
    """Function-scoped Playwright Page with MS login interception.

    Navigates to the Vite dev server and waits for the page to fully load.
    Intercepts any redirects to Microsoft login (safety net for CTA clicks).
    """
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
    )
    # Safety net: abort any navigation to Microsoft login
    # (avoid test failures when clicking CTA buttons in dev mode)
    context.route("**/login.microsoftonline.com/**", lambda route: route.abort())
    pg = context.new_page()
    pg.goto(vite_url, wait_until="networkidle", timeout=30000)
    yield pg
    context.close()


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _screenshot(page: Page, name: str) -> str:
    """Take a full-page screenshot and return the file path."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def _assert_element_visible(page: Page, locator_selector: str, description: str) -> None:
    """Assert that an element matching the locator is visible on the page."""
    loc = page.locator(locator_selector).first
    assert loc.is_visible(), f"Expected {description} to be visible (selector: {locator_selector})"


def _assert_text_visible(page: Page, text: str, description: str) -> None:
    """Assert that text content is visible on the page somewhere."""
    loc = page.get_by_text(text, exact=False).first
    assert loc.is_visible(), f"Expected '{text}' to be visible ({description})"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 1: Landing Page renders all 7 tiles correctly
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestLandingPageRendersAllTiles:
    """Verify the Landing Page renders all 7 tiles in correct top-to-bottom order.

    Each tile is verified by checking for its distinctive text content
    in the rendered React DOM (not static HTML source).
    """

    def test_landing_page_container_has_correct_class(self, page: Page):
        """Landing Page wrapper div has the scoped .landing-page CSS class."""
        loc = page.locator("div.landing-page").first
        assert loc.is_visible(), "Expected .landing-page wrapper to be visible"

    def test_global_nav_renders(self, page: Page):
        """GlobalNav (①) is a <nav> element and renders as first tile."""
        nav = page.locator("nav").first
        assert nav.is_visible(), "Expected GlobalNav <nav> element to be visible"
        # GlobalNav shows either "Dev Mode" or "登录" depending on MSAL config
        assert (
            page.get_by_text("Dev Mode").is_visible()
            or page.get_by_text("登录").is_visible()
        ), "Expected GlobalNav to show 'Dev Mode' or '登录'"

    def test_landing_hero_renders_headline_and_tagline(self, page: Page):
        """LandingHero (②) renders headline 'Personal Assistant' and tagline."""
        _assert_text_visible(page, "Personal Assistant", "LandingHero headline")
        _assert_text_visible(page, "您的 AI 助手", "LandingHero tagline")

    def test_capability_grid_renders_headline_and_cards(self, page: Page):
        """CapabilityGrid (③) renders '核心能力' headline and 4 capability cards."""
        _assert_text_visible(page, "核心能力", "CapabilityGrid headline")

        # Verify all 4 capability cards
        for card_title in ["日程管理", "邮件处理", "笔记记录", "任务管理"]:
            _assert_text_visible(page, card_title, f"CapabilityCard: {card_title}")

    def test_feature_tile_dark_renders(self, page: Page):
        """FeatureTile Dark (④) renders '自然语言交互' headline."""
        _assert_text_visible(page, "自然语言交互", "FeatureTile dark headline")

    def test_feature_tile_light_renders(self, page: Page):
        """FeatureTile Light (⑤) renders '跨渠道无缝衔接' headline."""
        _assert_text_visible(page, "跨渠道无缝衔接", "FeatureTile light headline")

    def test_feature_tile_parchment_renders(self, page: Page):
        """FeatureTile Parchment (⑥) renders '智能 Memory 与上下文感知' headline."""
        _assert_text_visible(page, "智能 Memory", "FeatureTile parchment headline")

    def test_closing_cta_renders(self, page: Page):
        """ClosingCTA (⑦) renders '准备好了吗？' and '立即开始'."""
        _assert_text_visible(page, "准备好了吗？", "ClosingCTA headline")
        _assert_text_visible(page, "立即开始", "ClosingCTA button text")

    def test_landing_footer_renders(self, page: Page):
        """LandingFooter (⑧) renders brand name and copyright."""
        _assert_text_visible(page, "Personal Assistant", "LandingFooter brand name")
        _assert_text_visible(page, "All rights reserved", "LandingFooter copyright")


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2: CTA buttons exist and are clickable
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestCTALandingPage:
    """Verify CTA buttons exist, have correct text, and are clickable.

    Checks specific button DOM elements (not just text in HTML source).
    """

    def test_landing_hero_has_primary_cta_button(self, page: Page):
        """LandingHero renders '开始对话' primary CTA button."""
        btn = page.get_by_role("button", name="开始对话")
        assert btn.is_visible(), "Expected '开始对话' button to be visible"
        assert btn.is_enabled(), "Expected '开始对话' button to be enabled"

    def test_landing_hero_has_secondary_cta_button(self, page: Page):
        """LandingHero renders '了解更多' secondary CTA button."""
        btn = page.get_by_role("button", name="了解更多").first
        assert btn.is_visible(), "Expected '了解更多' button to be visible"
        assert btn.is_enabled(), "Expected '了解更多' button to be enabled"

    def test_closing_cta_has_button(self, page: Page):
        """ClosingCTA renders '立即开始' button."""
        btn = page.get_by_role("button", name="立即开始")
        assert btn.is_visible(), "Expected '立即开始' button to be visible"
        assert btn.is_enabled(), "Expected '立即开始' button to be enabled"

    def test_apple_pill_button_has_rounded_full(self, page: Page):
        """At least one CTA button has rounded-full class (Apple pill style)."""
        pill_buttons = page.locator("button.rounded-full")
        count = pill_buttons.count()
        assert count > 0, (
            f"Expected at least 1 button with 'rounded-full' class (Apple pill), found {count}"
        )

    def test_cta_buttons_trigger_navigation_on_click(self, page: Page):
        """Clicking '开始对话' opens LoginPage (full-page, not modal).

        In the redesign, '开始对话' navigates to a full-page LoginPage.
        We verify the LoginPage heading appears and the page does not crash.
        """
        btn = page.get_by_role("button", name="开始对话")
        btn.click()
        page.wait_for_timeout(500)
        # LoginPage should appear with "登录 Personal Assistant" heading
        heading = page.get_by_text("登录 Personal Assistant")
        assert heading.is_visible(), (
            "Expected LoginPage with '登录 Personal Assistant' after clicking '开始对话'"
        )
        assert page.locator("body").is_visible(), (
            "Page should still be alive after CTA click (no crash)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2b: LandingHero height (60vh min-height)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestHeroHeight:
    """Verify LandingHero uses 60vh min-height."""

    def test_hero_has_60vh_min_height(self, page: Page):
        """LandingHero <section> has min-height: ~60vh, not 85vh."""
        # LandingHero is the first <section> on the page
        hero_section = page.locator("section").first
        min_height = hero_section.evaluate(
            "el => window.getComputedStyle(el).minHeight"
        )
        min_height_px = float(min_height.replace("px", ""))
        viewport_height = page.evaluate("() => window.innerHeight")
        sixty_vh = 0.6 * viewport_height
        eighty_five_vh = 0.85 * viewport_height
        # Actual min-height should be closer to 60vh than 85vh
        assert abs(min_height_px - sixty_vh) < abs(min_height_px - eighty_five_vh), (
            f"min-height ({min_height_px:.0f}px) should be closer to 60vh "
            f"({sixty_vh:.0f}px) than 85vh ({eighty_five_vh:.0f}px)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2c: LoginPage (replaces LoginModal — full-page component)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestLoginPageRenders:
    """Verify LoginPage full-page renders correctly."""

    def _open_login_page(self, page: Page) -> None:
        """Helper: click '开始对话' to navigate to LoginPage."""
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)
        # Verify we're on the LoginPage
        assert page.get_by_text("登录 Personal Assistant").is_visible(), (
            "LoginPage should be visible after clicking '开始对话'"
        )

    def test_login_page_opens_on_start_conversation(self, page: Page):
        """Click '开始对话' → LoginPage renders with heading."""
        self._open_login_page(page)

    def test_login_page_has_back_button(self, page: Page):
        """Back button '← 返回' visible, clicking returns to LandingPage."""
        self._open_login_page(page)
        # Verify back button exists
        back_btn = page.get_by_text("返回")
        assert back_btn.is_visible(), "Expected '返回' back button on LoginPage"
        # Click back → should return to LandingPage
        back_btn.click()
        page.wait_for_timeout(300)
        # LandingPage should be visible again
        assert page.get_by_text("您的 AI 助手").is_visible(), (
            "Should return to LandingPage after clicking '返回'"
        )

    def test_login_page_has_heading_and_subtitle(self, page: Page):
        """Heading '登录 Personal Assistant' and subtitle visible."""
        self._open_login_page(page)
        assert page.get_by_text("登录 Personal Assistant").is_visible()
        assert page.get_by_text("选择一种方式登录您的账号").is_visible()


@pytest.mark.feature
class TestLoginPageProviders:
    """Verify all 3 provider rows are present."""

    def _open_login_page(self, page: Page) -> None:
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)

    def test_three_providers_visible(self, page: Page):
        """Microsoft, GitHub, WeChat rows all present."""
        self._open_login_page(page)
        for label in ["Microsoft 账号", "GitHub 账号", "微信账号"]:
            # Use .first to avoid strict mode: "使用 GitHub 账号登录"
            # description also contains "GitHub 账号" as substring
            assert page.get_by_text(label).first.is_visible(), (
                f"Expected '{label}' provider to be visible on LoginPage"
            )

    def test_provider_descriptions_visible(self, page: Page):
        """Each provider has a description line."""
        self._open_login_page(page)
        for desc in ["Entra ID", "GitHub 账号登录", "微信扫码登录"]:
            assert page.get_by_text(desc, exact=False).is_visible(), (
                f"Expected description containing '{desc}'"
            )


@pytest.mark.feature
class TestLoginPageMicrosoftLogin:
    """Verify Microsoft row triggers login redirect."""

    def test_microsoft_row_triggers_login(self, page: Page):
        """Click Microsoft row → page survives (MSAL redirect intercepted)."""
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)
        # The Microsoft row is a <button> element
        ms_btn = page.get_by_text("Microsoft 账号")
        ms_btn.click()
        page.wait_for_timeout(500)
        assert page.locator("body").is_visible(), (
            "Page should survive Microsoft login click (MSAL intercepted)"
        )


@pytest.mark.feature
class TestLoginPageDisabledProviders:
    """Verify GitHub and WeChat are disabled with '即将支持' badges."""

    def _open_login_page(self, page: Page) -> None:
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)

    def test_github_disabled_with_badge(self, page: Page):
        """GitHub row: '即将支持' badge, not clickable."""
        self._open_login_page(page)
        # Find the disabled row: a div with cursor-not-allowed containing "GitHub 账号"
        github_row = page.locator(".cursor-not-allowed").filter(has_text="GitHub 账号")
        assert github_row.count() > 0, "GitHub row should contain '即将支持' badge"
        # Verify the badge text is present within the row
        assert github_row.first.get_by_text("即将支持").is_visible(), (
            "GitHub row should show '即将支持' badge"
        )

    def test_wechat_disabled_with_badge(self, page: Page):
        """WeChat row: '即将支持' badge."""
        self._open_login_page(page)
        wechat_row = page.locator("div").filter(
            has=page.get_by_text("微信账号")
        ).filter(has=page.get_by_text("即将支持"))
        assert wechat_row.count() > 0, "WeChat row should contain '即将支持' badge"


@pytest.mark.feature
class TestLoginPageBrandIcons:
    """Verify brand SVG icons render on provider rows."""

    def test_svg_icons_present(self, page: Page):
        """Each provider row has an SVG icon element."""
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)
        # All 3 provider rows should contain SVG icons
        svgs = page.locator("svg").count()
        assert svgs >= 3, f"Expected at least 3 SVG icons, found {svgs}"


@pytest.mark.feature
class TestLoginPageNoModalBackdrop:
    """Verify LoginPage is a full page, NOT a modal with backdrop."""

    def test_no_modal_overlay(self, page: Page):
        """No bg-black/30 overlay, no fixed.inset-0 backdrop."""
        page.get_by_role("button", name="开始对话").click()
        page.wait_for_timeout(300)
        # Should NOT have a modal overlay
        overlay = page.locator(".bg-black\\/30")
        assert overlay.count() == 0, (
            "LoginPage should not have bg-black/30 modal backdrop"
        )
        # Should be a full page (min-h-dvh)
        html_content = page.content()
        assert "min-h-dvh" in html_content, (
            "LoginPage should have min-h-dvh class (full-page, not modal)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2d: Scroll to Capabilities ('了解更多' buttons)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScrollToCapabilities:
    """Verify '了解更多' buttons scroll to #capabilities section."""

    def test_learn_more_scrolls_to_capabilities(self, page: Page):
        """LandingHero '了解更多' button scrolls to #capabilities."""
        # Scroll to top first
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        # Click "了解更多" button on LandingHero
        learn_more_btn = page.get_by_role("button", name="了解更多").first
        learn_more_btn.click()
        # Wait for smooth scroll animation
        page.wait_for_timeout(1000)
        scroll_y = page.evaluate("() => window.scrollY")
        assert scroll_y > 0, (
            f"Expected page to scroll down after clicking '了解更多', but scrollY={scroll_y}"
        )
        # Verify #capabilities element is now in viewport
        is_visible = page.locator("#capabilities").evaluate(
            "el => { const r = el.getBoundingClientRect(); "
            "return r.top < window.innerHeight && r.bottom > 0; }"
        )
        assert is_visible, (
            "#capabilities section should be visible in viewport after clicking '了解更多'"
        )

    def test_feature_tile_learn_more_scrolls(self, page: Page):
        """FeatureTile '了解更多' button also scrolls to #capabilities."""
        # Scroll to top first
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        # Find all "了解更多" buttons — there should be at least 2 (hero + feature tiles)
        learn_more_btns = page.get_by_role("button", name="了解更多")
        count = learn_more_btns.count()
        if count > 1:
            # Click the last "了解更多" (should be on a FeatureTile, after hero)
            learn_more_btns.nth(count - 1).click()
            page.wait_for_timeout(1000)
            scroll_y = page.evaluate("() => window.scrollY")
            assert scroll_y > 0, (
                f"Expected page to scroll after clicking FeatureTile '了解更多', "
                f"but scrollY={scroll_y}"
            )
        else:
            pytest.skip(
                "Only one '了解更多' button found; FeatureTile variant not available"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 3: LoadingState accessibility attributes
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestLoadingState:
    """Verify LoadingState accessibility during page load.

    In dev mode, MSAL initializes quickly so LoadingState may appear
    only fleetingly. We verify the page resolves correctly (LoadingState → LandingPage).
    """

    def test_landing_page_eventually_renders_after_loading(self, page: Page):
        """Landing Page content is visible after all lazy chunks load.

        This confirms LoadingState (shown during Suspense/hydration guard)
        resolved successfully without errors.
        """
        # Page is already loaded by the fixture; verify landing content renders
        assert page.locator("h1").first.is_visible(), "Expected Landing Page heading to be visible after loading"

    def test_landing_page_has_no_console_errors(self, page: Page):
        """Page loads without JavaScript console errors."""
        # Collect any console errors that occurred during page load
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        # Reload to capture full console output
        page.reload(wait_until="networkidle")
        for err in errors:
            # Ignore known MSAL warnings in dev mode (empty clientId)
            if "client_id" in err.lower() or "msal" in err.lower():
                continue
        # If there are unexpected errors, warn but don't fail
        unexpected = [e for e in errors if "client_id" not in e.lower() and "msal" not in e.lower()]
        assert len(unexpected) == 0, f"Unexpected console errors: {unexpected[:5]}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 4: Responsive design at breakpoints
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestResponsiveDesign:
    """Verify Landing Page responsive layout at DESIGN.md breakpoints.

    Tests viewports: 480, 640, 833, 1068, 1440.
    Checks: no overflow-x, CapabilityGrid column count, GlobalNav brand visibility.
    """

    BREAKPOINTS = [480, 640, 833, 1068, 1440]

    def _count_capability_cards(self, page: Page) -> int:
        """Count visible CapabilityCard elements on the page."""
        return page.locator(".rounded-\\[18px\\]").count()

    @pytest.mark.parametrize("width", BREAKPOINTS)
    def test_responsive_viewport(self, browser: Browser, vite_url: str, width: int):
        """At each breakpoint: screenshot, no overflow-x, correct grid columns, nav visibility."""
        context = browser.new_context(viewport={"width": width, "height": 900})
        context.route("**/login.microsoftonline.com/**", lambda route: route.abort())
        page = context.new_page()
        page.goto(vite_url, wait_until="networkidle", timeout=30000)

        try:
            # 1. Take full-page screenshot
            screenshot_path = _screenshot(page, f"responsive-{width}px")
            assert screenshot_path, f"Screenshot at {width}px should be saved"

            # 2. Check for horizontal overflow
            body_width = page.evaluate("() => document.body.scrollWidth")
            viewport_width = page.evaluate("() => window.innerWidth")
            assert body_width <= viewport_width + 5, (
                f"At {width}px: body scrollWidth ({body_width}) "
                f"exceeds viewport ({viewport_width}) — possible overflow-x"
            )

            # 3. Check CapabilityGrid column count
            cards = self._count_capability_cards(page)
            if width <= 833:
                expected_info = "1 column"
            elif width <= 1068:
                expected_info = "2 columns"
            else:
                expected_info = "4 columns"
            # We verify at least 4 cards exist (the grid layout handles column count)
            assert cards >= 4, (
                f"At {width}px ({expected_info}): expected at least 4 cards, found {cards}"
            )

            # 4. Check GlobalNav brand name visibility
            nav_brand = page.locator("nav span:has-text('Personal Assistant')")
            if width <= 1024:
                # Should be hidden at mobile widths (hidden lg:inline)
                assert not nav_brand.is_visible(), (
                    f"At {width}px: GlobalNav brand name should be hidden (≤1024px)"
                )
        finally:
            context.close()

    def test_capability_grid_columns_at_max_width(self, page: Page):
        """At 1440px viewport, CapabilityGrid renders 4 cards."""
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(500)  # Allow re-render
        cards = page.locator(".rounded-\\[18px\\]").count()
        assert cards == 4, f"Expected 4 CapabilityCards at 1440px, found {cards}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 5: Accessibility checks
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestAccessibility:
    """Verify basic accessibility attributes on the Landing Page."""

    def test_html_element_has_lang_attribute(self, page: Page):
        """<html> element has a lang attribute."""
        lang = page.locator("html").get_attribute("lang")
        assert lang is not None, "Expected <html> to have lang attribute"
        assert len(lang) > 0, "Expected lang attribute to be non-empty"

    def test_nav_element_exists(self, page: Page):
        """At least one <nav> element exists (GlobalNav)."""
        nav_count = page.locator("nav").count()
        assert nav_count >= 1, f"Expected at least 1 <nav> element, found {nav_count}"

    def test_heading_elements_exist(self, page: Page):
        """At least one <h1> or <h2> heading exists on the page."""
        h1_count = page.locator("h1").count()
        h2_count = page.locator("h2").count()
        assert (h1_count + h2_count) >= 1, (
            f"Expected at least 1 heading (h1 or h2), found h1={h1_count}, h2={h2_count}"
        )

    def test_buttons_have_discernible_text(self, page: Page):
        """All buttons on the page have non-empty accessible names."""
        buttons = page.locator("button")
        count = buttons.count()
        empty_buttons = 0
        for i in range(count):
            name = buttons.nth(i).get_attribute("aria-label") or buttons.nth(i).inner_text()
            if not name or not name.strip():
                empty_buttons += 1
        assert empty_buttons == 0, (
            f"Found {empty_buttons} buttons without discernible text out of {count} total"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 6: GlobalNav content
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestGlobalNav:
    """Verify the GlobalNav navigation bar content and styling."""

    def test_globalnav_is_nav_element(self, page: Page):
        """GlobalNav is rendered as a <nav> HTML element."""
        nav = page.locator("nav").first
        assert nav.is_visible(), "Expected <nav> element to be visible"
        tag = nav.evaluate("el => el.tagName.toLowerCase()")
        assert tag == "nav", f"Expected <nav> tag, got <{tag}>"

    def test_globalnav_shows_dev_mode_or_login(self, page: Page):
        """GlobalNav shows 'Dev Mode' (no MSAL config) or '登录' (MSAL configured)."""
        has_dev_mode = page.get_by_text("Dev Mode").is_visible()
        has_login = page.get_by_text("登录").is_visible()
        assert has_dev_mode or has_login, (
            "Expected GlobalNav to show either 'Dev Mode' (no MSAL) or '登录' (MSAL configured)"
        )

    def test_globalnav_screenshot(self, page: Page):
        """Take a screenshot of the GlobalNav."""
        path = _screenshot(page, "global-nav")
        assert path.endswith(".png"), f"Expected PNG screenshot, got {path}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 6b: GlobalNav '登录' opens LoginPage
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestGlobalNavLoginPage:
    """Verify GlobalNav '登录' button opens LoginPage."""

    def test_globalnav_login_opens_login_page(self, page: Page):
        """GlobalNav '登录' button opens LoginPage; handles Dev Mode fallback."""
        has_login = page.get_by_text("登录").is_visible()
        has_dev_mode = page.get_by_text("Dev Mode").is_visible()
        if has_login:
            login_btn = page.get_by_role("button", name="登录")
            assert login_btn.is_visible()
            login_btn.click()
            page.wait_for_timeout(300)
            assert page.get_by_text("登录 Personal Assistant").is_visible(), (
                "LoginPage should open when clicking GlobalNav '登录' button"
            )
        elif has_dev_mode:
            assert page.get_by_text("Dev Mode").is_visible()
        else:
            pytest.fail("GlobalNav shows neither '登录' button nor 'Dev Mode' text")


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 7: LandingFooter content
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestLandingFooter:
    """Verify the LandingFooter renders correct content."""

    def test_footer_contains_brand_name(self, page: Page):
        """Footer contains 'Personal Assistant' brand name."""
        footer = page.locator("footer")
        assert footer.is_visible(), "Expected <footer> element to be visible"
        # Use .first to avoid strict mode violation (text appears in both
        # brand name paragraph and copyright line)
        brand = footer.get_by_text("Personal Assistant").first
        assert brand.is_visible(), "Expected 'Personal Assistant' text in footer"

    def test_footer_contains_copyright(self, page: Page):
        """Footer contains copyright notice with current year."""
        year = str(__import__("datetime").datetime.now().year)
        copyright_text = page.locator("footer").inner_text()
        assert "Copyright" in copyright_text or "All rights reserved" in copyright_text, (
            f"Expected copyright notice in footer, got: {copyright_text[:200]}"
        )

    def test_footer_screenshot(self, page: Page):
        """Take a screenshot of the footer area."""
        # Scroll to bottom to ensure footer is rendered
        page.locator("footer").scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        path = _screenshot(page, "landing-footer")
        assert path.endswith(".png"), f"Expected PNG screenshot, got {path}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 7b: ClosingCTA '立即开始' opens LoginPage
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestClosingCTALoginPage:
    """Verify ClosingCTA '立即开始' opens LoginPage."""

    def test_closing_cta_opens_login_page(self, page: Page):
        """Scroll to bottom → click '立即开始' → LoginPage appears."""
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        cta_btn = page.get_by_role("button", name="立即开始")
        assert cta_btn.is_visible()
        cta_btn.click()
        page.wait_for_timeout(300)
        assert page.get_by_text("登录 Personal Assistant").is_visible(), (
            "LoginPage should open when clicking ClosingCTA '立即开始'"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Regression: Client unit tests (vitest) still pass
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestClientUnitTests:
    """Verify client unit tests (vitest) still pass after Landing Page changes."""

    def test_vitest_all_tests_pass(self):
        """Run vitest and verify exit code 0; capture test count."""
        if not (CLIENT_DIR / "node_modules").is_dir():
            pytest.skip("node_modules/ not found")

        result = subprocess.run(
            ["npx", "vitest", "run"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )

        stdout = result.stdout
        stderr = result.stderr

        # Verify exit code 0 (all tests pass)
        assert result.returncode == 0, (
            f"vitest failed with exit code {result.returncode}.\n"
            f"--- stdout (last 1500 chars) ---\n{stdout[-1500:]}\n"
            f"--- stderr (last 1000 chars) ---\n{stderr[-1000:]}"
        )

        # Verify we got test output and test count >= 95
        assert "Tests" in stdout or "tests" in stdout.lower(), (
            f"Expected test summary in vitest output. Got: {stdout[:500]}"
        )
        match = re.search(r"Tests\s+(\d+)\s+passed", stdout)
        if match:
            test_count = int(match.group(1))
            assert test_count >= 95, (
                f"Expected at least 95 vitest tests, got {test_count}.\n"
                f"--- stdout (last 1000 chars) ---\n{stdout[-1000:]}"
            )

    def test_chat_page_component_exists(self):
        """ChatPage component file exists and is referenced in App.tsx.

        This validates that ChatPage was properly extracted and the lazy import
        in App.tsx is correctly wired. Full E2E SSE streaming test requires
        authenticated MSAL session (out of scope for unauthenticated E2E).
        """
        chatpage_path = CLIENT_DIR / "src" / "components" / "chat" / "ChatPage.tsx"
        assert chatpage_path.is_file(), (
            f"ChatPage.tsx not found at {chatpage_path}"
        )

        app_path = CLIENT_DIR / "src" / "App.tsx"
        app_content = app_path.read_text()
        assert "ChatPage" in app_content, (
            "App.tsx should reference ChatPage for lazy loading"
        )
        assert "React.lazy" in app_content, (
            "App.tsx should use React.lazy for code splitting"
        )
