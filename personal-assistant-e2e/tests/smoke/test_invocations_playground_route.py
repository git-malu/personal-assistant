"""Smoke coverage for the current /invocations/playground route."""

import httpx
import pytest

pytestmark = [pytest.mark.smoke]


@pytest.mark.regression
def test_invocations_playground_no_trailing_slash_redirects(
    service_process,
):
    """GET /invocations/playground redirects to the mounted Chainlit path."""
    service_process.start()

    with httpx.Client(follow_redirects=False, timeout=10.0) as client:
        response = client.get(f"{service_process.url}/invocations/playground")

        assert response.status_code == 307, (
            "Expected /invocations/playground to redirect to the trailing-slash "
            f"mount, got {response.status_code}"
        )
        assert response.headers.get("location") == "/invocations/playground/", (
            "Expected redirect Location to be /invocations/playground/, "
            f"got: {response.headers.get('location')}"
        )

        response_slash = client.get(f"{service_process.url}/invocations/playground/")
        assert response_slash.status_code == 200, (
            "Baseline failed: GET /invocations/playground/ returned "
            f"{response_slash.status_code}"
        )
        assert "text/html" in response_slash.headers.get("content-type", "")


@pytest.mark.regression
def test_invocations_playground_ui_loads_correctly(service_process):
    """Verify the current Chainlit Playground mount returns an HTML shell."""
    service_process.start()

    with httpx.Client(follow_redirects=True, timeout=10.0) as client:
        response = client.get(f"{service_process.url}/invocations/playground/")
        assert response.status_code == 200

        html = response.text
        # Chainlit delivers an SPA shell
        assert "<!doctype html>" in html.lower() or "<html" in html.lower(), (
            "Chainlit Playground should return HTML content"
        )
