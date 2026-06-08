"""Regression test for bug-2: SPA Fallback Not Working.

Related: personal-assistant-meta/issues/bugs/bug-2-spa-fallback-not-working/

Starlette 1.2.1's StaticFiles(html=True) does NOT provide root-level index.html
fallback for arbitrary paths. Client-side routes like /chat return 404.

When fixed: GET /chat, /settings, etc. should return 200 with index.html content.
"""

import httpx
import pytest


# Import shared ServiceProcess fixture from e2e conftest.
# pytest automatically discovers conftest.py in the e2e root directory.
from conftest import ServiceProcess


@pytest.mark.regression
@pytest.mark.slow
class TestBug2_SPAFallbackNotWorking:
    """Verify SPA fallback behavior for client-side routes.

    Currently FAILING (returns 404): the StaticFiles(html=True) in Starlette 1.2.1
    does not fall back to root index.html for paths like /chat.
    """

    PORT = 18721

    @pytest.fixture
    def service_url(self):
        """Start the service via ServiceProcess and return its base URL."""
        import subprocess
        from pathlib import Path

        # Ensure dist exists before starting the service
        dist_dir = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "personal-assistant-client" / "dist"
        )
        if not (dist_dir / "index.html").exists():
            subprocess.run(
                ["npm", "run", "build"],
                cwd=str(dist_dir.parent),
                check=True,
                timeout=120,
            )

        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_root_serves_index_html(self, service_url):
        """Baseline: GET / should still serve index.html."""
        resp = httpx.get(f"{service_url}/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text

    def test_chat_route_serves_index_html(self, service_url):
        """GET /chat should serve index.html (SPA fallback). Currently FAILS with 404."""
        resp = httpx.get(f"{service_url}/chat")
        assert resp.status_code == 200, f"Expected 200 SPA fallback, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text
        assert 'id="root"' in resp.text

    def test_settings_route_serves_index_html(self, service_url):
        """GET /settings should serve index.html (SPA fallback). Currently FAILS with 404."""
        resp = httpx.get(f"{service_url}/settings")
        assert resp.status_code == 200, f"Expected 200 SPA fallback, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text

    def test_api_routes_still_work_with_static_mount(self, service_url):
        """API routes must still work even when SPA fallback is broken."""
        resp = httpx.get(f"{service_url}/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
