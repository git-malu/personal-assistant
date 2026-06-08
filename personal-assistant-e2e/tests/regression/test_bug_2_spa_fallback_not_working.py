"""Regression test for bug-2: SPA Fallback Not Working.

Related: personal-assistant-meta/issues/bugs/bug-2-spa-fallback-not-working/

NOTE (refactor-2): Bug-2 is now INVALID. The behavior it tested — SPA fallback
via StaticFiles(html=True) serving index.html for client-side routes like /chat,
/settings, and / — was intentionally removed in refactor-2 (Remove Web Chat
Static File Serving). The StaticFiles mount, SPAFallbackMiddleware, and
COPY of dist/ are all gone. GET / now returns 404 by design.

These tests are preserved as historical documentation but are skipped.
"""

import httpx
import pytest

from conftest import ServiceProcess


@pytest.mark.regression
@pytest.mark.slow
class TestBug2_SPAFallbackNotWorking:
    """Verify SPA fallback behavior for client-side routes.

    ALL TESTS SKIPPED after refactor-2: the SPA fallback behavior was
    removed by design. StaticFiles mount and SPAFallbackMiddleware are gone.
    GET /, /chat, /settings now all return 404 — this is expected.
    """

    PORT = 18721

    @pytest.fixture
    def service_url(self):
        """Start the service via ServiceProcess and return its base URL.

        Note: unlike the original fixture, we no longer run `npm run build`
        because dist/ is no longer required by the service (StaticFiles
        was removed in refactor-2).
        """
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles mount removed, "
               "GET / now returns 404 by design."
    )
    def test_root_serves_index_html(self, service_url):
        """Baseline: GET / should still serve index.html.

        SKIPPED: refactor-2 removed StaticFiles. GET / now returns 404.
        """
        resp = httpx.get(f"{service_url}/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: SPA fallback removed, "
               "client-side routes like /chat now return 404 by design."
    )
    def test_chat_route_serves_index_html(self, service_url):
        """GET /chat should serve index.html (SPA fallback). Currently FAILS with 404.

        SKIPPED: refactor-2 removed SPA fallback entirely.
        """
        resp = httpx.get(f"{service_url}/chat")
        assert resp.status_code == 200, f"Expected 200 SPA fallback, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text
        assert 'id="root"' in resp.text

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: SPA fallback removed, "
               "client-side routes like /settings now return 404 by design."
    )
    def test_settings_route_serves_index_html(self, service_url):
        """GET /settings should serve index.html (SPA fallback). Currently FAILS with 404.

        SKIPPED: refactor-2 removed SPA fallback entirely.
        """
        resp = httpx.get(f"{service_url}/settings")
        assert resp.status_code == 200, f"Expected 200 SPA fallback, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text

    def test_api_routes_still_work_with_static_mount(self, service_url):
        """API routes must still work even when SPA fallback is broken.

        This test still passes after refactor-2: /ping still works.
        However, we keep it running because it documents that the API
        plumbing continues to work correctly.
        """
        resp = httpx.get(f"{service_url}/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
