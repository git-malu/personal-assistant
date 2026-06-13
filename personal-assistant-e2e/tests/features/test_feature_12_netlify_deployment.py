"""E2E tests for Feature 12 — Netlify Deployment.

Verifies:
- CORS environment variable (CORS_ALLOWED_ORIGINS) at E2E/HTTP level
- netlify.toml configuration syntax and semantics
- npm run build artifact integrity
- SPA fallback simulation via local Python HTTP server
- Regression: ensure existing CORS and build tests still pass (manual step E)

Coverage note:
- CORS middleware registration, preflight, and static origin tests are already
  covered by TestScenario1_CORSIntegration in test_feature_chore_1_agentarts_deploy.py.
- Build + TypeScript tests are already covered by TestScenario4_FrontendBuild.
- SSE endpoint tests are covered by TestScenario2_SSEBackendIntegration.
- This file adds tests specifically for the env-var-driven CORS and the
  Netlify deployment configuration that did NOT exist before feature-12.
"""

import importlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Paths ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
NETLIFY_TOML = CLIENT_DIR / "netlify.toml"
DIST_DIR = CLIENT_DIR / "dist"

# Ensure service code is importable
_SERVICE_SRC = str(SERVICE_DIR)
if _SERVICE_SRC not in sys.path:
    sys.path.insert(0, _SERVICE_SRC)

# Default CORS origin from the service's hardcoded fallback
OBS_DEFAULT_ORIGIN = (
    "https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"
)


# ═════════════════════════════════════════════════════════════════════════
# Helper — create a TestClient with CORS env var applied
# ═════════════════════════════════════════════════════════════════════════


def _make_cors_test_client(cors_origins: str | None) -> tuple:
    """Create a FastAPI TestClient with CORS_ALLOWED_ORIGINS env var set.

    Uses monkeypatch-like env manipulation + importlib.reload so the
    module-level os.getenv("CORS_ALLOWED_ORIGINS") picks up the new value.
    LLM init is mocked to avoid real API calls during lifespan startup.

    Args:
        cors_origins: Value for CORS_ALLOWED_ORIGINS env var.
                      Pass None to delete the env var.

    Returns:
        (TestClient, old_value) — old_value is the previous env var value
        (or None) so the caller can restore it.
    """
    old_value = os.environ.get("CORS_ALLOWED_ORIGINS")

    if cors_origins is None:
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
    else:
        os.environ["CORS_ALLOWED_ORIGINS"] = cors_origins

    # Ensure a dummy API key so the lifespan doesn't crash on missing config
    old_api_key = os.environ.get("MAAS_API_KEY")
    os.environ["MAAS_API_KEY"] = "dummy-e2e-test-key"

    try:
        import app.main as app_main

        importlib.reload(app_main)

        with patch("app.llm_config.init_chat_model", return_value=MagicMock()):
            from fastapi.testclient import TestClient

            client = TestClient(app_main.app, raise_server_exceptions=False)

        return client, old_value, old_api_key
    except Exception:
        # Restore env on error before re-raising
        if old_value is not None:
            os.environ["CORS_ALLOWED_ORIGINS"] = old_value
        else:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        if old_api_key is not None:
            os.environ["MAAS_API_KEY"] = old_api_key
        else:
            os.environ.pop("MAAS_API_KEY", None)
        raise


def _restore_cors_env(old_value: str | None, old_api_key: str | None):
    """Restore CORS_ALLOWED_ORIGINS and MAAS_API_KEY env vars to their original state."""
    if old_value is not None:
        os.environ["CORS_ALLOWED_ORIGINS"] = old_value
    else:
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)

    if old_api_key is not None:
        os.environ["MAAS_API_KEY"] = old_api_key
    else:
        os.environ.pop("MAAS_API_KEY", None)

    # Reload app.main to restore default CORS config
    import app.main as app_main

    importlib.reload(app_main)


# ═════════════════════════════════════════════════════════════════════════
# A. CORS Environment Variable Testing at E2E level (via TestClient)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestCORSEnvVarE2E:
    """Test CORS_ALLOWED_ORIGINS env var behaviour via HTTP (TestClient).

    These tests verify that the CORS middleware actually responds with
    the correct Access-Control-Allow-Origin headers based on the env var,
    exercising the full FastAPI middleware stack.

    NOTE: Unit-level tests for the env var parsing logic already exist in
    personal-assistant-service/tests/test_main.py::TestCORSEnvVar.
    These E2E tests add the HTTP response layer on top.
    """

    # ── A1: multiple custom origins ─────────────────────────────────────

    def test_a1_multiple_custom_origins_via_env(self):
        """A1: Multiple comma-separated origins in CORS_ALLOWED_ORIGINS.

        - Origin a.example.com → echoed in ACAO header
        - Origin b.example.com → echoed in ACAO header
        - Origin evil.example.com → NOT echoed (disallowed)
        """
        client, old_val, old_key = _make_cors_test_client(
            "https://a.example.com,https://b.example.com"
        )
        try:
            # Allowed origin A
            resp = client.get("/ping", headers={"Origin": "https://a.example.com"})
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            assert (
                resp.headers.get("access-control-allow-origin")
                == "https://a.example.com"
            ), (
                f"Expected ACAO=https://a.example.com, "
                f"got {resp.headers.get('access-control-allow-origin')!r}"
            )

            # Allowed origin B
            resp = client.get("/ping", headers={"Origin": "https://b.example.com"})
            assert resp.status_code == 200
            assert (
                resp.headers.get("access-control-allow-origin")
                == "https://b.example.com"
            ), (
                f"Expected ACAO=https://b.example.com, "
                f"got {resp.headers.get('access-control-allow-origin')!r}"
            )

            # Disallowed origin — no ACAO header
            resp = client.get("/ping", headers={"Origin": "https://evil.example.com"})
            assert resp.status_code == 200
            acao = resp.headers.get("access-control-allow-origin", "")
            assert acao == "", (
                f"Disallowed origin must NOT produce ACAO header, got {acao!r}"
            )
        finally:
            _restore_cors_env(old_val, old_key)

    # ── A2: empty CORS_ALLOWED_ORIGINS falls back to default ────────────

    def test_a2_empty_env_falls_back_to_default(self):
        """A2: Empty CORS_ALLOWED_ORIGINS → fallback to hardcoded OBS domain.

        An empty string is falsy in Python, so the ``if _env_origins``
        check evaluates to False and _default_origins is used.
        """
        client, old_val, old_key = _make_cors_test_client("")
        try:
            # Allowed: OBS default origin
            resp = client.get("/ping", headers={"Origin": OBS_DEFAULT_ORIGIN})
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            assert (
                resp.headers.get("access-control-allow-origin") == OBS_DEFAULT_ORIGIN
            ), (
                f"Empty CORS_ALLOWED_ORIGINS should fall back to default "
                f"({OBS_DEFAULT_ORIGIN!r}), "
                f"got {resp.headers.get('access-control-allow-origin')!r}"
            )

            # Credentials header still present
            assert resp.headers.get("access-control-allow-credentials") == "true"

            # Disallowed origin — no ACAO header
            resp = client.get(
                "/ping", headers={"Origin": "https://evil.example.com"}
            )
            assert resp.status_code == 200
            acao = resp.headers.get("access-control-allow-origin", "")
            assert acao == "", (
                f"Disallowed origin must NOT produce ACAO header, got {acao!r}"
            )
        finally:
            _restore_cors_env(old_val, old_key)

    # ── A3: Netlify-specific origin ─────────────────────────────────────

    def test_a3_netlify_origin(self):
        """A3: CORS_ALLOWED_ORIGINS set to a Netlify deploy domain.

        Simulates the production scenario where the service is configured
        to accept requests from a Netlify-hosted frontend.
        """
        client, old_val, old_key = _make_cors_test_client(
            "https://personal-assistant.netlify.app"
        )
        try:
            # Allowed: Netlify origin
            resp = client.get(
                "/ping",
                headers={"Origin": "https://personal-assistant.netlify.app"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            assert (
                resp.headers.get("access-control-allow-origin")
                == "https://personal-assistant.netlify.app"
            ), (
                f"Expected ACAO=https://personal-assistant.netlify.app, "
                f"got {resp.headers.get('access-control-allow-origin')!r}"
            )

            # Credentials still true
            assert resp.headers.get("access-control-allow-credentials") == "true"

            # Disallowed origin — no ACAO
            resp = client.get(
                "/ping", headers={"Origin": "https://evil.example.com"}
            )
            assert resp.status_code == 200
            acao = resp.headers.get("access-control-allow-origin", "")
            assert acao == "", (
                f"Disallowed origin must NOT produce ACAO header, got {acao!r}"
            )
        finally:
            _restore_cors_env(old_val, old_key)


# ═════════════════════════════════════════════════════════════════════════
# B. netlify.toml Validation
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestNetlifyTomlValidation:
    """Validate netlify.toml for correct TOML syntax and deploy semantics."""

    def test_b1_netlify_toml_is_valid_toml(self):
        """B1: netlify.toml is syntactically valid TOML with required sections.

        Parses with Python's built-in tomllib (3.11+) and verifies:
        - [build] section with base, command, publish
        - [[redirects]] array with from, to, status
        """
        assert NETLIFY_TOML.exists(), f"netlify.toml not found at {NETLIFY_TOML}"
        raw = NETLIFY_TOML.read_text(encoding="utf-8")

        import tomllib

        data = tomllib.loads(raw)

        # ── [build] section ──
        assert "build" in data, (
            f"No [build] section in netlify.toml. Top-level keys: {list(data.keys())}"
        )
        build = data["build"]
        for key in ("base", "command", "publish"):
            assert key in build, f"[build] missing '{key}' key. Build section: {build}"

        # ── [[redirects]] array ──
        assert "redirects" in data, (
            f"No [[redirects]] in netlify.toml. Top-level keys: {list(data.keys())}"
        )
        redirects = data["redirects"]
        assert isinstance(redirects, list), (
            f"redirects should be a list ([[redirects]]), got {type(redirects).__name__}"
        )
        assert len(redirects) >= 1, (
            f"Expected at least one redirect rule, got {len(redirects)}"
        )

        first = redirects[0]
        for key in ("from", "to", "status"):
            assert key in first, (
                f"First redirect rule missing '{key}'. Rule: {first}"
            )

    def test_b2_redirect_rule_is_spa_fallback(self):
        """B2: Redirect rule semantics — SPA fallback, not HTTP redirect.

        from = "/*", to = "/index.html", status = 200 means:
        - All non-file paths rewrite to /index.html (client-side routing)
        - Status 200 (not 301/302) — the URL stays in the browser
        """
        raw = NETLIFY_TOML.read_text(encoding="utf-8")

        import tomllib

        data = tomllib.loads(raw)

        # Find the rule that handles catch-all SPA routing
        spa_rules = [r for r in data.get("redirects", []) if r.get("from") == "/*"]
        assert len(spa_rules) == 1, (
            f"Expected exactly one redirect rule for '/*', got {len(spa_rules)}"
        )
        rule = spa_rules[0]
        assert rule["to"] == "/index.html", (
            f"Expected to=\"/index.html\" for SPA entry point, got {rule['to']!r}"
        )
        assert rule["status"] == 200, (
            f"Expected status=200 (rewrite, not redirect), got {rule['status']!r}"
        )

    def test_b3_build_config_paths_valid(self):
        """B3: Build config paths resolve correctly in the monorepo.

        - base = "personal-assistant-client" → directory exists
        - command = "npm run build" → "build" script exists in package.json
        - publish = "dist" → matches Vite build output directory
        """
        raw = NETLIFY_TOML.read_text(encoding="utf-8")

        import tomllib

        data = tomllib.loads(raw)
        build = data["build"]

        # base directory
        base_dir = PROJECT_ROOT / build["base"]
        assert base_dir.is_dir(), (
            f"Build base '{build['base']}' does not exist relative to "
            f"repo root ({PROJECT_ROOT})"
        )

        # command — extract script name from "npm run <script>"
        assert build["command"] == "npm run build", (
            f"Expected command='npm run build', got {build['command']!r}"
        )

        package_json = CLIENT_DIR / "package.json"
        assert package_json.exists(), f"package.json not found at {package_json}"
        pkg = json.loads(package_json.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        assert "build" in scripts, (
            f"No 'build' script in package.json. Available: {list(scripts.keys())}"
        )

        # publish directory name
        assert build["publish"] == "dist", (
            f"Expected publish='dist', got {build['publish']!r}"
        )


# ═════════════════════════════════════════════════════════════════════════
# C. npm run build Verification
# ═════════════════════════════════════════════════════════════════════════
#
# NOTE: These tests overlap with Scenario 4 in
#   test_feature_chore_1_agentarts_deploy.py::TestScenario4_FrontendBuild.
# They are included here to verify the Netlify build contract independently.
# If node/npm are not available, all tests are skipped.
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestNpmRunBuild:
    """Verify npm run build produces correct artifacts for Netlify deploy."""

    @pytest.fixture(autouse=True)
    def _ensure_deps(self):
        """Skip all tests if Node.js or npm are unavailable."""
        import shutil

        if not shutil.which("node"):
            pytest.skip("node not available — cannot build frontend")
        if not shutil.which("npm"):
            pytest.skip("npm not available — cannot build frontend")
        if not (CLIENT_DIR / "node_modules").is_dir():
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(
                    f"npm install failed in client dir: {result.stderr[-300:]}"
                )

    def test_c1_build_exits_zero(self):
        """C1: npm run build exits with code 0."""
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"npm run build failed with code {result.returncode}:\n"
            f"STDERR: {result.stderr[-600:]}\n"
            f"STDOUT: {result.stdout[-600:]}"
        )

    def test_c2_dist_directory_exists(self):
        """C1: dist/ directory exists after build."""
        if not DIST_DIR.is_dir():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"npm run build failed: {result.stderr[-300:]}"
            )
        assert DIST_DIR.is_dir(), f"dist/ directory not found at {DIST_DIR}"

    def test_c3_dist_index_html_exists(self):
        """C1: dist/index.html exists after build."""
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"npm run build failed: {result.stderr[-300:]}"
            )
        assert (DIST_DIR / "index.html").is_file(), (
            "dist/index.html not found after build"
        )

    def test_c4_assets_has_js_and_css(self):
        """C1: dist/assets/ contains non-empty JS and CSS files."""
        if not DIST_DIR.is_dir():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"npm run build failed: {result.stderr[-300:]}"
            )

        assets_dir = DIST_DIR / "assets"
        assert assets_dir.is_dir(), (
            f"assets/ directory not found at {assets_dir}. "
            f"dist/ contents: {[p.name for p in DIST_DIR.iterdir()]}"
        )

        js_files = list(assets_dir.glob("*.js"))
        css_files = list(assets_dir.glob("*.css"))

        assert len(js_files) >= 1, (
            f"No JS files in {assets_dir}. "
            f"Contents: {[p.name for p in assets_dir.iterdir()]}"
        )
        assert len(css_files) >= 1, (
            f"No CSS files in {assets_dir}. "
            f"Contents: {[p.name for p in assets_dir.iterdir()]}"
        )

        # All asset files must be non-empty
        for f in js_files + css_files:
            assert f.stat().st_size > 0, f"Asset file {f.name} is empty (0 bytes)"


# ═════════════════════════════════════════════════════════════════════════
# D. SPA Fallback Simulation (Local Static Server)
# ═════════════════════════════════════════════════════════════════════════
#
# Python's http.server does NOT implement SPA fallback — this is deliberate.
# Netlify handles the /* → /index.html rewrite in production via [[redirects]].
# These tests verify static serving works and document the expected local
# behaviour (404 on non-file paths).
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestSPAFallbackSimulation:
    """Simulate Netlify SPA deployment locally with Python http.server.

    Python's http.server has NO SPA fallback capability. These tests
    verify static asset serving and document that SPA routes return 404
    locally (Netlify's redirects handle this in production).
    """

    PORT = 18760

    @pytest.fixture
    def static_server_url(self):
        """Start Python http.server on dist/ and return base URL."""
        import http.server
        import socketserver

        # Ensure build artifacts exist
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(
                    f"Cannot start static server — build failed: "
                    f"{result.stderr[-300:]}"
                )

        # Start server on dist/ directory
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(DIST_DIR), **kwargs)

        socketserver.TCPServer.allow_reuse_address = True
        httpd = socketserver.TCPServer(("127.0.0.1", self.PORT), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.3)

        url = f"http://127.0.0.1:{self.PORT}"
        yield url

        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)

    def test_d1_root_returns_200_html(self, static_server_url):
        """D1: GET / returns 200 with text/html content type."""
        import httpx

        resp = httpx.get(f"{static_server_url}/", follow_redirects=False)
        assert resp.status_code == 200, (
            f"GET / expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type, (
            f"Expected text/html, got content-type: {content_type!r}"
        )

    def test_d2_static_assets_served(self, static_server_url):
        """D1: Static files under /assets/ are served correctly."""
        import httpx

        assets_dir = DIST_DIR / "assets"
        if not assets_dir.is_dir():
            pytest.skip("No assets/ directory to test static serving")

        js_files = list(assets_dir.glob("*.js"))
        if not js_files:
            pytest.skip("No JS files in assets/ to test")

        asset_name = js_files[0].name
        asset_url = f"{static_server_url}/assets/{asset_name}"
        resp = httpx.get(asset_url)
        assert resp.status_code == 200, (
            f"GET {asset_url} expected 200, got {resp.status_code}"
        )
        assert len(resp.content) > 0, (
            f"Static asset {asset_name} returned empty body"
        )

    def test_d3_spa_route_returns_404_locally(self, static_server_url):
        """D1: GET /chat returns 404 — Python http.server has no SPA fallback.

        This is EXPECTED behaviour. Netlify's [[redirects]] in netlify.toml
        handles SPA fallback (/* → /index.html, 200) in production.
        """
        import httpx

        resp = httpx.get(f"{static_server_url}/chat")
        assert resp.status_code == 404, (
            f"Python http.server expected 404 for /chat (no SPA fallback). "
            f"Got {resp.status_code}. "
            f"If this is 200, something changed — verify the server config."
        )
