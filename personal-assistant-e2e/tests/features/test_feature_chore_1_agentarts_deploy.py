"""E2E tests for Chore 1 — AgentArts Deploy.

Verifies the three-domain integration deployed in the chore/agentarts-deploy branch:
- Service: CORS middleware, /ping health check, /api/chat/stream SSE endpoint
- Client: SSE chat adapter (TypeScript), VITE_API_BASE_URL env injection, utils.ts
- Infra: CDKTF stack (OBS bucket for static website hosting)

Test scenarios from task:
  1. CORS + Frontend Integration (TestClient-based)
  2. SSE Chat Adapter + Backend Integration (Subprocess-based)
  3. Infra Stack Validity (cdktf synth)
  4. Frontend Build + Backend API Contract
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
INFRA_DIR = PROJECT_ROOT / "personal-assistant-infra"
DIST_DIR = CLIENT_DIR / "dist"

# Expected CORS origin from AgentArts Deploy specification
ALLOWED_ORIGIN = "https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"
DISALLOWED_ORIGIN = "https://evil.example.com"


# ═════════════════════════════════════════════════════════════════════════
# Scenario 1: CORS + Frontend Integration (TestClient-based)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario1_CORSIntegration:
    """Verify CORS middleware is configured and responds correctly.

    Uses the e2e_client fixture (FastAPI TestClient) to exercise the full
    middleware stack without starting a subprocess.
    """

    def test_cors_middleware_is_registered(self, e2e_client):
        """Verify CORSMiddleware is present in the app middleware stack."""
        client, _ = e2e_client
        app = client.app

        from fastapi.middleware.cors import CORSMiddleware

        cors_middlewares = [
            m for m in app.user_middleware
            if m.cls == CORSMiddleware
        ]
        assert len(cors_middlewares) >= 1, (
            f"CORSMiddleware not found in app middleware. "
            f"Middleware stack: {[m.cls.__name__ for m in app.user_middleware]}"
        )

    def test_cors_allowed_origin_list(self, e2e_client):
        """Verify the allowed origins list contains the expected OBS domain."""
        client, _ = e2e_client
        app = client.app

        from fastapi.middleware.cors import CORSMiddleware

        cors_mw = [
            m for m in app.user_middleware
            if m.cls == CORSMiddleware
        ][0]
        allowed_origins = cors_mw.kwargs.get("allow_origins", [])
        assert ALLOWED_ORIGIN in allowed_origins, (
            f"Expected origin {ALLOWED_ORIGIN!r} in allow_origins, "
            f"got: {allowed_origins!r}"
        )

    def test_cors_allow_credentials(self, e2e_client):
        """Verify allow_credentials is set to True."""
        client, _ = e2e_client
        app = client.app

        from fastapi.middleware.cors import CORSMiddleware

        cors_mw = [
            m for m in app.user_middleware
            if m.cls == CORSMiddleware
        ][0]
        assert cors_mw.kwargs.get("allow_credentials") is True, (
            "Expected allow_credentials=True in CORS middleware"
        )

    def test_cors_allow_methods_wildcard(self, e2e_client):
        """Verify allow_methods is set to ["*"]."""
        client, _ = e2e_client
        app = client.app
        from fastapi.middleware.cors import CORSMiddleware
        cors_mw = [m for m in app.user_middleware if m.cls == CORSMiddleware][0]
        assert cors_mw.kwargs.get("allow_methods") == ["*"], (
            f"Expected allow_methods=['*'], got {cors_mw.kwargs.get('allow_methods')!r}"
        )

    def test_cors_allow_headers_wildcard(self, e2e_client):
        """Verify allow_headers is set to ["*"]."""
        client, _ = e2e_client
        app = client.app
        from fastapi.middleware.cors import CORSMiddleware
        cors_mw = [m for m in app.user_middleware if m.cls == CORSMiddleware][0]
        assert cors_mw.kwargs.get("allow_headers") == ["*"], (
            f"Expected allow_headers=['*'], got {cors_mw.kwargs.get('allow_headers')!r}"
        )

    def test_preflight_options_ping_with_allowed_origin(self, e2e_client):
        """Preflight OPTIONS /ping with allowed origin returns proper CORS headers."""
        client, _ = e2e_client

        resp = client.options(
            "/ping",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200, (
            f"OPTIONS /ping failed: {resp.status_code} {resp.text[:200]}"
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == ALLOWED_ORIGIN, (
            f"Expected Access-Control-Allow-Origin={ALLOWED_ORIGIN!r}, "
            f"got {acao!r}"
        )
        assert "access-control-allow-methods" in resp.headers, (
            f"Preflight response missing Access-Control-Allow-Methods header. "
            f"Headers: {dict(resp.headers)}"
        )
        assert resp.headers.get("access-control-allow-credentials") == "true", (
            f"Preflight response missing Access-Control-Allow-Credentials: true. "
            f"Headers: {dict(resp.headers)}"
        )

    def test_get_ping_with_allowed_origin_has_cors_header(self, e2e_client):
        """GET /ping with allowed origin includes Access-Control-Allow-Origin header."""
        client, _ = e2e_client

        resp = client.get("/ping", headers={"Origin": ALLOWED_ORIGIN})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == ALLOWED_ORIGIN, (
            f"Expected Access-Control-Allow-Origin={ALLOWED_ORIGIN!r} "
            f"in GET /ping response, got {acao!r}"
        )
        assert resp.headers.get("access-control-allow-credentials") == "true", (
            f"Expected Access-Control-Allow-Credentials: true in GET /ping with allowed origin, "
            f"got {resp.headers.get('access-control-allow-credentials')!r}"
        )

    def test_get_ping_with_disallowed_origin_no_cors_header(self, e2e_client):
        """GET /ping with disallowed origin does NOT return Access-Control-Allow-Origin."""
        client, _ = e2e_client

        resp = client.get("/ping", headers={"Origin": DISALLOWED_ORIGIN})
        assert resp.status_code == 200

        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == "", (
            f"Disallowed origin should produce no CORS header, got {acao!r}"
        )

    def test_get_ping_without_origin_header(self, e2e_client):
        """GET /ping without Origin header still returns 200 (no CORS needed)."""
        client, _ = e2e_client

        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.fixture
    def cors_client(self):
        """Create a TestClient with a properly mocked AgentHandler that returns successfully.

        Unlike the generic e2e_client (which mocks init_chat_model and causes
        handler 500), this fixture injects a mock handler directly into app.state,
        allowing us to test CORS headers on successful POST /invocations.

        The lifespan does NOT run under TestClient, so AgentHandler is never
        instantiated — we bypass it entirely by setting app.state.agent_handler.
        """
        import os

        class MockAgentHandler:
            async def handle(self, message, user_id="anonymous", session_id=None):
                return f"echo: {message}"
            async def handle_stream(self, message, user_id="anonymous"):
                import json
                yield f'data: {json.dumps({"token": "test", "done": False})}\n\n'
                yield f'data: {json.dumps({"token": "", "done": True})}\n\n'

        # Save and restore env to avoid leaking state between tests
        original_key = os.environ.get("MAAS_API_KEY")
        os.environ["MAAS_API_KEY"] = "dummy-e2e-test-key"

        try:
            from app.main import app
            from fastapi.testclient import TestClient

            handler = MockAgentHandler()
            app.state.agent_handler = handler

            client = TestClient(app, raise_server_exceptions=False)
            yield client
        finally:
            if original_key is not None:
                os.environ["MAAS_API_KEY"] = original_key
            else:
                os.environ.pop("MAAS_API_KEY", None)

    def test_post_invocations_with_allowed_origin_has_cors_header(self, cors_client):
        """POST /invocations with allowed origin includes CORS headers."""
        resp = cors_client.post(
            "/invocations",
            json={"message": "Hello"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert resp.status_code == 200, (
            f"POST /invocations failed: {resp.status_code} {resp.text[:200]}"
        )
        assert resp.json() == {"response": "echo: Hello"}

        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == ALLOWED_ORIGIN, (
            f"Expected Access-Control-Allow-Origin={ALLOWED_ORIGIN!r} "
            f"in POST /invocations response, got {acao!r}"
        )
        assert resp.headers.get("access-control-allow-credentials") == "true", (
            f"Expected Access-Control-Allow-Credentials: true in POST /invocations "
            f"with allowed origin, got {resp.headers.get('access-control-allow-credentials')!r}"
        )

    def test_preflight_options_invocations_with_allowed_origin(self, e2e_client):
        """Preflight OPTIONS /invocations with allowed origin returns CORS headers."""
        client, _ = e2e_client

        resp = client.options(
            "/invocations",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200, (
            f"OPTIONS /invocations failed: {resp.status_code}"
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == ALLOWED_ORIGIN, (
            f"Expected Access-Control-Allow-Origin={ALLOWED_ORIGIN!r}, "
            f"got {acao!r}"
        )
        assert "access-control-allow-methods" in resp.headers, (
            f"Preflight response missing Access-Control-Allow-Methods header"
        )
        assert resp.headers.get("access-control-allow-credentials") == "true", (
            f"Preflight response missing Access-Control-Allow-Credentials: true"
        )


# ═════════════════════════════════════════════════════════════════════════
# Scenario 2: SSE Chat Adapter + Backend Integration (Subprocess-based)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestScenario2_SSEBackendIntegration:
    """Verify SSE streaming endpoint works with a real subprocess service.

    Starts uvicorn via the service_process fixture from conftest.py.
    Since we use a dummy API key, LLM calls may fail (500) but we verify
    the endpoint plumbing, content types, and error handling.
    """

    PORT = 18750

    @pytest.fixture
    def service_url(self):
        """Start the service subprocess and return its base URL."""
        from conftest import ServiceProcess

        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_sse_endpoint_returns_200_or_500_not_crash(self, service_url):
        """GET /api/chat/stream?q=test returns a response (200 or 500 — not crash).

        With a dummy API key, the LLM may fail (500), but the endpoint
        plumbing must work and not crash the process.
        """
        resp = httpx.get(f"{service_url}/api/chat/stream?q=test")
        assert resp.status_code in (200, 500), (
            f"Expected 200 or 500 from SSE endpoint, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_content_type_is_event_stream(self, service_url):
        """When SSE responds successfully, content-type is text/event-stream."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=hello")
        # If LLM works (200), verify content-type. If LLM fails (500), skip.
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, (
                f"Expected text/event-stream, got: {content_type}"
            )

    def test_sse_empty_query_returns_400(self, service_url):
        """GET /api/chat/stream?q= (empty) returns 400."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=")
        assert resp.status_code == 400, (
            f"Expected 400 for empty query, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_missing_query_returns_400(self, service_url):
        """GET /api/chat/stream without q param returns 400."""
        resp = httpx.get(f"{service_url}/api/chat/stream")
        assert resp.status_code == 400, (
            f"Expected 400 for missing query, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_has_correct_streaming_headers(self, service_url):
        """SSE response includes proper streaming headers."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=hello")
        if resp.status_code == 200:
            assert resp.headers.get("cache-control") == "no-cache"
            assert resp.headers.get("connection") == "keep-alive"
            assert resp.headers.get("x-accel-buffering") == "no"

    def test_ping_endpoint_works_alongside_sse(self, service_url):
        """Health check /ping works while SSE endpoint exists."""
        resp = httpx.get(f"{service_url}/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════════
# Scenario 3: Infra Stack Validity (cdktf synth)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_InfraStackValidity:
    """Verify the CDKTF infrastructure stack synthesizes correctly.

    Validates:
    - cdktf synth exits successfully
    - Synthesized JSON contains expected OBS bucket configuration
    """

    @pytest.fixture(autouse=True)
    def _ensure_deps(self):
        """Skip if cdktf / npx not available."""
        if not shutil.which("npx"):
            pytest.skip("npx not available — cannot run cdktf synth")
        if not (INFRA_DIR / "node_modules").is_dir():
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(INFRA_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(
                    f"npm install failed in infra dir: {result.stderr[-300:]}"
                )

    def test_cdktf_synth_succeeds(self, tmp_path):
        """cdktf synth exits with code 0 and generates Terraform JSON."""
        result = subprocess.run(
            ["npx", "cdktf", "synth"],
            cwd=str(INFRA_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"cdktf synth failed with code {result.returncode}:\n"
            f"stderr: {result.stderr[-1000:]}\n"
            f"stdout: {result.stdout[-500:]}"
        )

        # Verify output directory exists with Terraform JSON
        cdktf_out = INFRA_DIR / "cdktf.out"
        assert cdktf_out.is_dir(), f"cdktf.out/ not found after synth at {cdktf_out}"

        stack_dirs = list(cdktf_out.glob("stacks/*"))
        assert len(stack_dirs) > 0, f"No stack directories found in cdktf.out/stacks/"

    def test_synthesized_json_has_obs_bucket_config(self):
        """The synthesized Terraform JSON contains expected OBS bucket settings."""
        cdktf_out = INFRA_DIR / "cdktf.out"

        # Run synth if cdktf.out doesn't exist yet
        if not cdktf_out.is_dir():
            result = subprocess.run(
                ["npx", "cdktf", "synth"],
                cwd=str(INFRA_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"cdktf synth failed: {result.stderr[-300:]}")

        # Find the Terraform JSON stack file
        stack_dirs = list(cdktf_out.glob("stacks/*"))
        if not stack_dirs:
            pytest.skip("No stack directories found in cdktf.out/")
            return

        stack_dir = stack_dirs[0]
        tf_json_path = stack_dir / "cdk.tf.json"

        if not tf_json_path.exists():
            # Old cdktf versions may use different naming
            alt_paths = list(stack_dir.glob("*.tf.json"))
            if alt_paths:
                tf_json_path = alt_paths[0]
            else:
                pytest.skip(f"No .tf.json file found in {stack_dir}")
                return

        tf_json = json.loads(tf_json_path.read_text(encoding="utf-8"))

        # Verify the JSON structure
        resource = tf_json.get("resource", {})

        # Find the OBS bucket resource
        obs_bucket_config = None
        for resource_type, resources in resource.items():
            if "obs_bucket" in resource_type:
                for _, config in resources.items():
                    obs_bucket_config = config
                    break

        assert obs_bucket_config is not None, (
            f"No obs_bucket resource found in Terraform JSON. "
            f"Available resource types: {list(resource.keys())}"
        )

        # Verify bucket name
        assert obs_bucket_config.get("bucket") == "personal-assistant-web-chat", (
            f"Expected bucket='personal-assistant-web-chat', "
            f"got {obs_bucket_config.get('bucket')!r}"
        )

        # Verify ACL
        assert obs_bucket_config.get("acl") == "public-read", (
            f"Expected acl='public-read', got {obs_bucket_config.get('acl')!r}"
        )

        # Verify versioning
        versioning = obs_bucket_config.get("versioning", {})
        assert versioning is True or versioning.get("enabled") is True or versioning == {"enabled": True}, (
            f"Expected versioning enabled, got {versioning!r}"
        )

        # Verify website config
        website = obs_bucket_config.get("website", {})
        assert website, f"No website config found in obs_bucket: {obs_bucket_config}"

        # index_document may be nested or top-level
        index_doc = website.get("index_document") or website.get("indexDocument")
        assert index_doc == "index.html", (
            f"Expected index_document='index.html', got {index_doc!r}. "
            f"Full website config: {website}"
        )

        error_doc = website.get("error_document") or website.get("errorDocument")
        assert error_doc == "index.html", (
            f"Expected error_document='index.html' (SPA fallback), "
            f"got {error_doc!r}. Full website config: {website}"
        )

    def test_output_has_website_endpoint(self):
        """cdktf synth output includes the OBS website endpoint."""
        cdktf_out = INFRA_DIR / "cdktf.out"

        if not cdktf_out.is_dir():
            result = subprocess.run(
                ["npx", "cdktf", "synth"],
                cwd=str(INFRA_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"cdktf synth failed: {result.stderr[-300:]}")

        stack_dirs = list(cdktf_out.glob("stacks/*"))
        if not stack_dirs:
            pytest.skip("No stack directories found in cdktf.out/")
            return

        stack_dir = stack_dirs[0]
        tf_json_path = stack_dir / "cdk.tf.json"
        if not tf_json_path.exists():
            alt_paths = list(stack_dir.glob("*.tf.json"))
            tf_json_path = alt_paths[0] if alt_paths else None
        if not tf_json_path or not tf_json_path.exists():
            pytest.skip(f"No .tf.json found in {stack_dir}")
            return

        tf_json = json.loads(tf_json_path.read_text(encoding="utf-8"))

        # Check outputs
        output = tf_json.get("output", {})
        website_output = output.get("website-endpoint", {})

        assert website_output, (
            f"No 'website-endpoint' output found. Available outputs: {list(output.keys())}"
        )
        output_value = website_output.get("value", "")
        # CDKTF outputs may use Terraform references (${...}) resolved at deploy time
        assert "obs-website" in output_value, (
            f"Website endpoint should contain 'obs-website', got: {output_value!r}"
        )
        assert "personal-assistant-web-chat" in output_value or "web-chat" in output_value, (
            f"Website endpoint output should reference the web-chat bucket, got: {output_value!r}"
        )


# ═════════════════════════════════════════════════════════════════════════
# Scenario 4: Frontend Build + Backend API Contract
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
class TestScenario4_FrontendBuild:
    """Verify the frontend builds correctly and aligns with the backend API contract.

    Validates:
    - TypeScript compilation passes (tsc --noEmit)
    - Production build succeeds (npm run build)
    - dist/index.html exists with proper structure
    - Built assets reference the correct API base URL
    """

    @pytest.fixture(autouse=True)
    def _ensure_deps(self):
        """Skip if Node.js/npm prerequisites are missing."""
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

    def test_typescript_compilation_passes(self):
        """npx tsc --noEmit succeeds (no TypeScript errors in chat-adapter.ts, utils.ts)."""
        result = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"TypeScript compilation failed with code {result.returncode}:\n"
            f"stderr: {result.stderr[-1000:]}\n"
            f"stdout: {result.stdout[-500:]}"
        )

    def test_npm_run_build_succeeds(self):
        """npm run build exits successfully and creates dist/index.html."""
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"npm run build failed with code {result.returncode}:\n"
            f"stderr: {result.stderr[-1000:]}\n"
            f"stdout: {result.stdout[-500:]}"
        )

        assert DIST_DIR.is_dir(), f"dist/ directory not found after build at {DIST_DIR}"
        assert (DIST_DIR / "index.html").exists(), "dist/index.html not found after build"

    def test_dist_index_html_has_proper_structure(self):
        """dist/index.html contains proper HTML structure for the SPA."""
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"npm run build failed: {result.stderr[-300:]}")

        content = (DIST_DIR / "index.html").read_text(encoding="utf-8")

        # Basic HTML structure
        assert "<!doctype html>" in content.lower() or "<!DOCTYPE html>" in content
        assert "<html" in content
        assert '<div id="root"></div>' in content or 'id="root"' in content
        assert "<script" in content, "Expected script tags in index.html"

        # Should reference assets
        assert "/assets/" in content, (
            f"Expected /assets/ references in built HTML. "
            f"Preview: {content[:500]}"
        )

    def test_dist_has_bundled_assets(self):
        """dist/assets/ contains bundled JS and CSS files."""
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"npm run build failed: {result.stderr[-300:]}")

        assets_dir = DIST_DIR / "assets"
        assert assets_dir.is_dir(), f"assets/ directory not found at {assets_dir}"

        js_files = list(assets_dir.glob("*.js"))
        css_files = list(assets_dir.glob("*.css"))

        assert len(js_files) >= 1, (
            f"No JS files found in {assets_dir}. "
            f"Contents: {[p.name for p in assets_dir.iterdir()]}"
        )
        assert len(css_files) >= 1, (
            f"No CSS files found in {assets_dir}. "
            f"Contents: {[p.name for p in assets_dir.iterdir()]}"
        )

        # Verify files are non-empty
        for js_file in js_files:
            assert js_file.stat().st_size > 0, f"JS file {js_file.name} is empty"
        for css_file in css_files:
            assert css_file.stat().st_size > 0, f"CSS file {css_file.name} is empty"

    def test_chat_adapter_exists_and_exports(self):
        """src/lib/chat-adapter.ts exists and is importable (via tsc check)."""
        adapter_path = CLIENT_DIR / "src" / "lib" / "chat-adapter.ts"
        assert adapter_path.exists(), f"chat-adapter.ts not found at {adapter_path}"

        content = adapter_path.read_text(encoding="utf-8")
        # Verify key patterns in the adapter
        assert "VITE_API_BASE_URL" in content, (
            "chat-adapter.ts should use VITE_API_BASE_URL env var"
        )
        assert "chatAdapter" in content, (
            "chat-adapter.ts should export chatAdapter"
        )
        assert "/api/chat/stream" in content, (
            "chat-adapter.ts should call /api/chat/stream endpoint"
        )
        assert "text/event-stream" in content, (
            "chat-adapter.ts should accept text/event-stream"
        )

    def test_vite_env_type_declaration_exists(self):
        """src/vite-env.d.ts declares VITE_API_BASE_URL type."""
        env_d_path = CLIENT_DIR / "src" / "vite-env.d.ts"
        assert env_d_path.exists(), f"vite-env.d.ts not found at {env_d_path}"

        content = env_d_path.read_text(encoding="utf-8")
        assert "VITE_API_BASE_URL" in content, (
            "vite-env.d.ts should declare VITE_API_BASE_URL"
        )
        assert "ImportMetaEnv" in content, (
            "vite-env.d.ts should extend ImportMetaEnv"
        )

    def test_env_production_template_exists(self):
        """.env.production contains VITE_API_BASE_URL template."""
        env_path = CLIENT_DIR / ".env.production"
        assert env_path.exists(), f".env.production not found at {env_path}"

        content = env_path.read_text(encoding="utf-8")
        assert "VITE_API_BASE_URL" in content, (
            ".env.production should define VITE_API_BASE_URL"
        )

    def test_utils_cn_function(self):
        """src/lib/utils.ts exports cn() via clsx + tailwind-merge."""
        utils_path = CLIENT_DIR / "src" / "lib" / "utils.ts"
        assert utils_path.exists(), f"utils.ts not found at {utils_path}"

        content = utils_path.read_text(encoding="utf-8")
        assert "export function cn" in content, (
            "utils.ts should export cn() function"
        )
        assert "clsx" in content, "utils.ts should use clsx"
        assert "twMerge" in content, "utils.ts should use tailwind-merge (twMerge)"
