"""Regression test for bug-3: /playground Endpoint Returns 404.

Related: personal-assistant-meta/issues/bugs/bug-3-playground-returns-404/ (RESOLVED)

BUG-3 was fixed by merging main (f51c0f7). The /playground endpoint now
serves Chainlit content. These tests verify the fix remains in place.
"""

import httpx
import pytest

from conftest import ServiceProcess


@pytest.mark.regression
@pytest.mark.slow
class TestBug3_PlaygroundReturns404:
    """Verify /playground endpoint availability.

    BUG-3 is now fixed — the Chainlit Playground code from main was merged,
    so /playground should return a valid response (200 or 302, not 404).
    """

    PORT = 18722

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

    def test_playground_returns_valid_response(self, service_url):
        """GET /playground should return 200 or 302 (not 404). BUG-3 is now fixed."""
        resp = httpx.get(f"{service_url}/playground", follow_redirects=False)
        assert resp.status_code != 404, (
            f"/playground should not return 404. Got: {resp.status_code}"
        )
        assert resp.status_code < 500, (
            f"/playground should not cause server error: {resp.status_code}"
        )

    def test_playground_does_not_crash_service(self, service_url):
        """Multiple /playground requests should not degrade service health."""
        for _ in range(3):
            httpx.get(f"{service_url}/playground", follow_redirects=False)
        # After /playground calls, ping should still work
        resp = httpx.get(f"{service_url}/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_root_still_serves_index_html(self, service_url):
        """Baseline: GET / should still serve the assistant-ui chat interface."""
        resp = httpx.get(f"{service_url}/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Personal Assistant" in resp.text
