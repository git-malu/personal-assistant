"""Regression test for bug-1: GET /playground (no trailing slash) returns 404.

Related: personal-assistant-meta/issues/bugs/bug-1-playground-trailing-slash-404/

FastAPI's app.mount() does not auto-redirect for mounted ASGI sub-apps.
GET /playground should redirect to /playground/ instead of returning 404.
"""

import httpx
import pytest


@pytest.mark.regression
def test_bug_1_playground_no_trailing_slash_returns_200_or_redirect(
    service_process,
):
    """GET /playground (no trailing slash) should return 200 or 307/308 redirect.

    Currently returns 404 due to Starlette mount behavior.
    Bug link: personal-assistant-meta/issues/bugs/bug-1-playground-trailing-slash-404/issue.md
    """
    service_process.start()

    with httpx.Client(follow_redirects=False, timeout=10.0) as client:
        # Test: /playground without trailing slash
        response = client.get(f"{service_process.url}/playground")

        # Fixed by a63a540: GET /playground now returns 307 Temporary Redirect to /playground/
        assert response.status_code == 307, (
            f"BUG-1 regression: GET /playground returned {response.status_code}, "
            f"expected 307 redirect to /playground/. "
            f"See: personal-assistant-meta/issues/bugs/bug-1-playground-trailing-slash-404/"
        )
        assert response.headers.get("location") == "/playground/", (
            f"BUG-1 regression: redirect Location should be /playground/, "
            f"got: {response.headers.get('location')}"
        )

        # Verify /playground/ works correctly as baseline
        response_slash = client.get(f"{service_process.url}/playground/")
        assert response_slash.status_code == 200, (
            f"Baseline failed: GET /playground/ returned {response_slash.status_code}"
        )
        assert "text/html" in response_slash.headers.get("content-type", "")


@pytest.mark.regression
def test_bug_1_playground_ui_loads_correctly(service_process):
    """Verify Chainlit Playground UI loads with proper HTML and assets.

    Sanity check that the Chainlit mount itself works correctly
    when accessed via the correct path (/playground/).
    """
    service_process.start()

    with httpx.Client(follow_redirects=True, timeout=10.0) as client:
        response = client.get(f"{service_process.url}/playground/")
        assert response.status_code == 200

        html = response.text
        # Chainlit delivers an SPA shell
        assert "<!doctype html>" in html.lower() or "<html" in html.lower(), (
            "Chainlit Playground should return HTML content"
        )
