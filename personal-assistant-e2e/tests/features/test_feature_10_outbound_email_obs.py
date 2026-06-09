"""E2E tests for Feature 10 — Outbound Email + OBS tools integration.

Covers:
  1. Tool registration verification (mocked create_deep_agent)
  2. System prompt content (Guard rules, capabilities, behavior guidelines)
  3. Tool import integrity (callability, names, async, docstrings)
  4. HTTP /invocations endpoint (normal, empty, missing, Chinese text)
  5. HTTP /api/chat/stream SSE endpoint (format, content, headers, error handling)
  6. HTTP /ping endpoint (health check + state isolation)
  7. Guard mechanism sensitivity marking (write safety section positioning)
  8. Email tool auth decorator configuration (scopes, provider, auth_flow)
  9. OBS tool auth decorator configuration (STS tokens, provider_name)

Tests run against the FastAPI app in-process via TestClient.
LLM-dependent behavioral tests (actual Guard enforcement) require a real LLM
and are NOT included — those are covered by Hermes-based integration tests.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CONFIG_YAML = SERVICE_DIR / "config.yaml"
CONFIG_YAML_BACKUP = SERVICE_DIR / "config.yaml.e2e-backup"

# Ensure service is on sys.path (conftest.py does this too, but be explicit)
_SERVICE_SRC = str(SERVICE_DIR)
if _SERVICE_SRC not in sys.path:
    sys.path.insert(0, _SERVICE_SRC)


# ═══════════════════════════════════════════════════════════════════════
# Config file management
# ═══════════════════════════════════════════════════════════════════════


def _backup_config():
    """Create a backup of config.yaml if it exists."""
    if CONFIG_YAML.exists() and not CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML), str(CONFIG_YAML_BACKUP))


def _restore_config():
    """Restore config.yaml from backup."""
    if CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML_BACKUP), str(CONFIG_YAML))
        CONFIG_YAML_BACKUP.unlink()


@pytest.fixture(autouse=True)
def manage_config():
    """Backup and restore config.yaml around the test module.

    Tests like TestScenario1_ToolRegistration._capture_tools() instantiate
    AgentHandler, which triggers get_model() → reads config.yaml from disk.
    This fixture ensures config.yaml is always restored to its original state.
    Mirrors the pattern from test_feature_1_1_web_chat.py.
    """
    _backup_config()
    yield
    _restore_config()


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


class FakeAgentHandler:
    """A fake AgentHandler with predictable streaming responses.

    Mirrors the pattern from test_feature_1_1_web_chat.py.
    """

    DEFAULT_TOKENS = ["Hello", " world", "!"]

    def __init__(self, tokens: list[str] | None = None):
        self._tokens = tokens or self.DEFAULT_TOKENS
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        return "".join(self._tokens)

    async def handle_stream(self, message: str, user_id: str = "anonymous"):
        self.stream_calls.append((message, user_id))
        for token in self._tokens:
            yield f'data: {json.dumps({"token": token, "done": False})}\n\n'
        yield f'data: {json.dumps({"token": "", "done": True})}\n\n'


@pytest.fixture
def fake_handler():
    """Create a FakeAgentHandler instance with recorded calls."""
    return FakeAgentHandler()


@pytest.fixture
async def test_app_client(fake_handler):
    """httpx AsyncClient for the FastAPI app with FakeAgentHandler.

    Uses ASGITransport to test the full FastAPI stack in-process.
    Patches AgentHandler in app.main so lifespan creates our fake.
    Sets MODEL_API_KEY and MAAS_API_KEY to satisfy llm_config validation.
    """
    os.environ.setdefault("MODEL_API_KEY", "test-key-for-e2e")
    os.environ.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")

    # Import app.main first so the module exists for patching,
    # then use patch.object which takes a real module reference.
    import app.main as app_main
    with patch.object(app_main, "AgentHandler", return_value=fake_handler):
        from app.main import app

        app.state.agent_handler = fake_handler

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1: Tool Registration
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario1_ToolRegistration:
    """Verify all 8 tools are registered in AgentHandler.

    Uses mocked create_deep_agent to capture the tools list passed to it,
    since the CompiledStateGraph returned by create_deep_agent doesn't
    expose tools as a public attribute.
    """

    @pytest.fixture(autouse=True)
    def _set_api_key_env(self, monkeypatch):
        """Set required env vars so AgentHandler.__init__ can create a model."""
        monkeypatch.setenv("MAAS_API_KEY", "dummy-e2e-test-key")

    def _capture_tools(self):
        """Instantiate AgentHandler with create_deep_agent + get_model mocked.

        Returns the tools list that was passed to create_deep_agent.
        Also patches get_model to avoid real LLM initialization.
        """
        with patch("app.agent_handler.create_deep_agent") as mock_create, \
             patch("app.agent_handler.get_model", return_value=MagicMock()):
            mock_create.return_value = MagicMock()
            from app.agent_handler import AgentHandler
            AgentHandler()
            # Extract the tools keyword argument
            call_kwargs = mock_create.call_args.kwargs
            return call_kwargs.get("tools", []), call_kwargs

    def test_eight_tools_registered(self):
        """AgentHandler.__init__ registers exactly 8 tools with correct names."""
        tools, _ = self._capture_tools()

        assert len(tools) == 8, (
            f"Expected exactly 8 tools, got {len(tools)}: "
            f"{[getattr(t, '__name__', str(t)) for t in tools]}"
        )

        # Verify tool names
        tool_names = {getattr(t, "__name__", str(t)) for t in tools}
        expected_names = {
            "list_emails",
            "get_email",
            "search_emails",
            "send_email",
            "draft_reply",
            "list_obs_objects",
            "get_obs_object",
            "get_obs_object_metadata",
        }

        missing = expected_names - tool_names
        unexpected = tool_names - expected_names

        assert not missing, f"Missing tools: {missing}"
        assert not unexpected, f"Unexpected tools: {unexpected}"

    def test_all_tools_are_callable(self):
        """Every registered tool is a callable function."""
        tools, _ = self._capture_tools()

        for tool in tools:
            assert callable(tool), (
                f"Tool {getattr(tool, '__name__', str(tool))} is not callable"
            )

    def test_tool_registration_order_matches_import_order(self):
        """Tools are registered in the order: email (5) then OBS (3)."""
        tools, _ = self._capture_tools()

        # First 5 should be email tools
        email_tool_names = {"list_emails", "get_email", "search_emails", "send_email", "draft_reply"}
        first_five = {getattr(t, "__name__", str(t)) for t in tools[:5]}
        assert first_five == email_tool_names, (
            f"Expected first 5 to be email tools, got {first_five}"
        )

        # Last 3 should be OBS tools
        obs_tool_names = {"list_obs_objects", "get_obs_object", "get_obs_object_metadata"}
        last_three = {getattr(t, "__name__", str(t)) for t in tools[5:]}
        assert last_three == obs_tool_names, (
            f"Expected last 3 to be OBS tools, got {last_three}"
        )

    def test_tools_passed_explicitly_to_create_deep_agent(self):
        """The 'tools' kwarg is explicitly passed to create_deep_agent."""
        _, kwargs = self._capture_tools()
        assert "tools" in kwargs, (
            "tools should be passed as a keyword argument to create_deep_agent"
        )
        tools = kwargs["tools"]
        assert len(tools) == 8, (
            f"Expected exactly 8 tools in create_deep_agent(tools=...), got {len(tools)}"
        )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2: System Prompt Content
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario2_SystemPrompt:
    """Verify SYSTEM_PROMPT contains Guard rules, capability descriptions,
    and behavior guidelines.

    Consolidates the original A2, C1, and C2 test classes into a single
    canonical system prompt verification class.  All Guard-rule and
    draft-flow checks live here; sensitivity-positioning tests remain in
    TestScenario7_GuardMechanism.
    """

    SYSTEM_PROMPT: str

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        """Load SYSTEM_PROMPT from agent_handler module."""
        from app.agent_handler import SYSTEM_PROMPT
        self.SYSTEM_PROMPT = SYSTEM_PROMPT

    # ── Section / capability headers ──────────────────────────────────

    def test_contains_email_section_header(self):
        """SYSTEM_PROMPT has '邮件处理' section."""
        assert "邮件处理" in self.SYSTEM_PROMPT, (
            "Missing: '邮件处理' section header"
        )

    def test_contains_obs_section_header(self):
        """SYSTEM_PROMPT has 'OBS 文件查询' section."""
        assert "OBS 文件查询" in self.SYSTEM_PROMPT, (
            "Missing: 'OBS 文件查询' section header"
        )

    def test_contains_write_operation_safety_section(self):
        """SYSTEM_PROMPT has '写操作安全规则' section."""
        assert "写操作安全规则" in self.SYSTEM_PROMPT, (
            "Missing: '写操作安全规则' section header"
        )

    def test_contains_behavior_guidelines(self):
        """SYSTEM_PROMPT has behavior guidelines section."""
        assert "行为准则" in self.SYSTEM_PROMPT, (
            "Missing: '行为准则' section header"
        )
        assert "中文" in self.SYSTEM_PROMPT, (
            "Missing: Chinese language instruction"
        )

    # ── Tool mentions ─────────────────────────────────────────────────

    def test_mentions_all_eight_tools(self):
        """SYSTEM_PROMPT mentions all 8 tool functions."""
        expected_tools = [
            "list_emails",
            "get_email",
            "search_emails",
            "send_email",
            "draft_reply",
            "list_obs_objects",
            "get_obs_object",
            "get_obs_object_metadata",
        ]
        for tool_name in expected_tools:
            assert tool_name in self.SYSTEM_PROMPT, (
                f"SYSTEM_PROMPT should mention tool: {tool_name}"
            )

    # ── Guard rules (send_email prohibition + draft flow) ─────────────

    def test_prohibits_direct_send_email(self):
        """SYSTEM_PROMPT forbids direct send_email on first request."""
        assert "禁止" in self.SYSTEM_PROMPT, "SYSTEM_PROMPT should contain guard rules"
        assert (
            "禁止**在用户首次请求时直接调用 send_email" in self.SYSTEM_PROMPT
            or "禁止在用户首次请求时直接调用 send_email" in self.SYSTEM_PROMPT
        ), "Missing: prohibition of direct send_email call"

    def test_requires_draft_reply_first(self):
        """SYSTEM_PROMPT mandates draft_reply before send_email."""
        assert (
            "必须先调用 draft_reply 创建草稿" in self.SYSTEM_PROMPT
        ), "Missing: '必须先调用 draft_reply 创建草稿'"

    def test_contains_confirmation_message(self):
        """SYSTEM_PROMPT tells agent to ask for user confirmation."""
        assert "确认发送请回复'发送'" in self.SYSTEM_PROMPT, (
            "Missing: confirmation prompt"
        )

    def test_describes_drafts_recovery_flow(self):
        """SYSTEM_PROMPT describes the complete 3-step Drafts recovery flow."""
        prompt = self.SYSTEM_PROMPT

        assert 'list_emails(folder="drafts", limit=1)' in prompt, (
            "Missing: step 1 — list latest draft from Drafts folder"
        )
        assert "get_email(draft_id)" in prompt, (
            "Missing: step 2 — read draft content"
        )
        assert "send_email(to=" in prompt, (
            "Missing: step 3 — send the email"
        )

    def test_describes_modification_flow(self):
        """SYSTEM_PROMPT describes how to handle user modification requests."""
        prompt = self.SYSTEM_PROMPT

        assert "修改" in prompt or "改成" in prompt, (
            "Missing: modification flow description"
        )
        assert "original_email_id" in prompt, (
            "Missing: extraction of original_email_id in modification flow"
        )

    def test_mentions_design_rationale(self):
        """SYSTEM_PROMPT includes design note about statelessness."""
        prompt = self.SYSTEM_PROMPT

        assert "设计说明" in prompt or "无法跨调用" in prompt or "独立的" in prompt, (
            "Missing: design rationale explaining why Drafts mechanism is needed"
        )
        assert "Drafts" in prompt, (
            "Missing: mention of Drafts folder as recovery mechanism"
        )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3: Tool Import Integrity
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario3_ToolImportIntegrity:
    """Verify tools can be imported and are callable functions."""

    EXPECTED_NAMES = {
        "list_emails", "get_email", "search_emails", "send_email", "draft_reply",
        "list_obs_objects", "get_obs_object", "get_obs_object_metadata",
    }

    def test_email_tools_are_callable(self):
        """All 5 email tools are importable and callable."""
        from app.tools.email_tools import (
            draft_reply, get_email, list_emails, search_emails, send_email,
        )

        tools = [list_emails, get_email, search_emails, send_email, draft_reply]
        for tool in tools:
            assert callable(tool), f"{tool} is not callable"
            name = tool.__name__
            assert name in self.EXPECTED_NAMES, f"Unexpected tool name: {name}"

    def test_obs_tools_are_callable(self):
        """All 3 OBS tools are importable and callable."""
        from app.tools.obs_tools import (
            get_obs_object, get_obs_object_metadata, list_obs_objects,
        )

        tools = [list_obs_objects, get_obs_object, get_obs_object_metadata]
        for tool in tools:
            assert callable(tool), f"{tool} is not callable"
            name = tool.__name__
            assert name in self.EXPECTED_NAMES, f"Unexpected tool name: {name}"

    def test_name_attribute_matches_expected(self):
        """Each imported function has the correct __name__."""
        from app.tools.email_tools import (
            draft_reply, get_email, list_emails, search_emails, send_email,
        )
        from app.tools.obs_tools import (
            get_obs_object, get_obs_object_metadata, list_obs_objects,
        )

        name_map = {
            list_emails: "list_emails",
            get_email: "get_email",
            search_emails: "search_emails",
            send_email: "send_email",
            draft_reply: "draft_reply",
            list_obs_objects: "list_obs_objects",
            get_obs_object: "get_obs_object",
            get_obs_object_metadata: "get_obs_object_metadata",
        }

        for tool, expected_name in name_map.items():
            assert tool.__name__ == expected_name, (
                f"Expected __name__='{expected_name}', got '{tool.__name__}'"
            )

    def test_email_tools_are_async_functions(self):
        """All email tools are async functions (coroutine functions)."""
        import inspect
        from app.tools.email_tools import (
            draft_reply, get_email, list_emails, search_emails, send_email,
        )

        for tool in [list_emails, get_email, search_emails, send_email, draft_reply]:
            assert inspect.iscoroutinefunction(tool) or hasattr(tool, "__wrapped__"), (
                f"Tool {tool.__name__} should be an async function or decorated wrapper"
            )

    def test_obs_tools_are_async_functions(self):
        """All OBS tools are async functions."""
        import inspect
        from app.tools.obs_tools import (
            get_obs_object, get_obs_object_metadata, list_obs_objects,
        )

        for tool in [list_obs_objects, get_obs_object, get_obs_object_metadata]:
            assert inspect.iscoroutinefunction(tool) or hasattr(tool, "__wrapped__"), (
                f"Tool {tool.__name__} should be an async function or decorated wrapper"
            )

    def test_tools_have_docstrings(self):
        """All tools have descriptive docstrings."""
        from app.tools.email_tools import (
            draft_reply, get_email, list_emails, search_emails, send_email,
        )
        from app.tools.obs_tools import (
            get_obs_object, get_obs_object_metadata, list_obs_objects,
        )

        all_tools = [
            list_emails, get_email, search_emails, send_email, draft_reply,
            list_obs_objects, get_obs_object, get_obs_object_metadata,
        ]
        for tool in all_tools:
            doc = (tool.__doc__ or "").strip()
            assert len(doc) > 0, f"Tool {tool.__name__} is missing a docstring"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4: HTTP /invocations Endpoint
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario4_HttpInvocations:
    """POST /invocations with normal, empty, missing, and Chinese messages."""

    @pytest.mark.asyncio
    async def test_normal_message_returns_200_with_response(self, test_app_client, fake_handler):
        """POST /invocations with normal message returns {"response": "..."}."""
        resp = await test_app_client.post(
            "/invocations",
            json={"message": "帮我看看收件箱"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        assert "response" in data, f"Response missing 'response' key: {data}"
        assert isinstance(data["response"], str), (
            f"Expected string response, got {type(data['response'])}"
        )
        assert len(data["response"]) > 0, "Response should not be empty"

    @pytest.mark.asyncio
    async def test_invocations_calls_handler_handle(self, test_app_client, fake_handler):
        """POST /invocations forwards message to handler.handle()."""
        await test_app_client.post(
            "/invocations",
            json={"message": "帮我看看收件箱"},
        )

        assert len(fake_handler.handle_calls) == 1, (
            f"Expected 1 handle call, got {len(fake_handler.handle_calls)}"
        )
        call_message, call_user_id, call_session_id = fake_handler.handle_calls[0]
        assert call_message == "帮我看看收件箱"
        assert call_user_id == "anonymous"  # default when no header

    @pytest.mark.asyncio
    async def test_chinese_message_passed_verbatim(self, test_app_client, fake_handler):
        """POST /invocations with Chinese text passes the message verbatim."""
        chinese_msg = "帮我查一下华为云OBS上logs目录下的文件"
        await test_app_client.post(
            "/invocations",
            json={"message": chinese_msg},
        )

        assert len(fake_handler.handle_calls) == 1
        assert fake_handler.handle_calls[0][0] == chinese_msg, (
            f"Chinese message was corrupted: expected '{chinese_msg}', "
            f"got '{fake_handler.handle_calls[0][0]}'"
        )

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self, test_app_client):
        """POST /invocations with {"message": ""} returns 400."""
        resp = await test_app_client.post(
            "/invocations",
            json={"message": ""},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        assert "detail" in data, f"Response missing 'detail' key: {data}"
        assert "message" in data["detail"].lower() or "required" in data["detail"].lower(), (
            f"Error detail should mention that message is required. Got: {data.get('detail')}"
        )

    @pytest.mark.asyncio
    async def test_missing_message_field_returns_400(self, test_app_client):
        """POST /invocations with {} (no 'message' key) returns 400."""
        resp = await test_app_client.post(
            "/invocations",
            json={},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for missing message field, got {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        assert "detail" in data, f"Response missing 'detail' key: {data}"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 5: HTTP /api/chat/stream SSE Endpoint
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario5_HttpApiChatStream:
    """GET /api/chat/stream SSE format, content, and error handling."""

    # ── Valid SSE responses ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_sse_content_type(self, test_app_client):
        """SSE endpoint returns text/event-stream."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )

        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected text/event-stream, got: {content_type}"
        )

    @pytest.mark.asyncio
    async def test_sse_has_data_prefix(self, test_app_client):
        """Every SSE line starts with 'data: '."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]
        assert len(lines) > 0, "SSE response should not be empty"

        for line in lines:
            assert line.startswith("data: "), (
                f"SSE line missing 'data: ' prefix: {line!r}"
            )

    @pytest.mark.asyncio
    async def test_sse_lines_are_valid_json(self, test_app_client):
        """Each SSE data payload is valid JSON."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]

        for line in lines:
            if line.startswith("data: "):
                payload = line[6:]  # strip "data: " prefix
                try:
                    json.loads(payload)
                except json.JSONDecodeError as e:
                    pytest.fail(
                        f"SSE data line is not valid JSON: {payload!r}. Error: {e}"
                    )

    @pytest.mark.asyncio
    async def test_sse_has_done_event(self, test_app_client):
        """SSE response ends with a done=true event."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]

        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        done_events = [e for e in events if e.get("done")]
        assert len(done_events) == 1, (
            f"Expected exactly 1 done event, got {len(done_events)}: {events}"
        )
        assert done_events[0]["done"] is True

    @pytest.mark.asyncio
    async def test_sse_has_token_events(self, test_app_client):
        """SSE response has at least one token event."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]

        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        tokens = [e for e in events if not e.get("done") and "token" in e]
        assert len(tokens) >= 1, (
            f"Expected at least 1 token event, got {len(tokens)}: {events}"
        )

    @pytest.mark.asyncio
    async def test_sse_calls_handler_stream(self, test_app_client, fake_handler):
        """/api/chat/stream forwards query to handler.handle_stream()."""
        await test_app_client.get("/api/chat/stream?q=Hello")

        assert len(fake_handler.stream_calls) == 1, (
            f"Expected 1 stream call, got {len(fake_handler.stream_calls)}"
        )
        assert fake_handler.stream_calls[0][0] == "Hello"

    @pytest.mark.asyncio
    async def test_sse_has_correct_headers(self, test_app_client):
        """SSE response has Cache-Control, Connection, and X-Accel-Buffering headers."""
        resp = await test_app_client.get("/api/chat/stream?q=Hello")
        assert resp.status_code == 200

        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"

    # ── Error handling ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_query_returns_400(self, test_app_client):
        """GET /api/chat/stream?q= returns 400."""
        resp = await test_app_client.get("/api/chat/stream?q=")
        assert resp.status_code == 400, (
            f"Expected 400 for empty query, got {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        assert "detail" in data, f"Response missing 'detail' key: {data}"

    @pytest.mark.asyncio
    async def test_missing_q_param_returns_400(self, test_app_client):
        """GET /api/chat/stream (no q param) returns 400 (or 422 for missing param)."""
        resp = await test_app_client.get("/api/chat/stream")
        # FastAPI may return 422 for missing required query param, or 400
        assert resp.status_code in (400, 422), (
            f"Expected 400 or 422, got {resp.status_code}: {resp.text[:200]}"
        )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 6: HTTP /ping Endpoint
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario6_HttpPing:
    """GET /ping returns 200 and {"status": "ok"}."""

    @pytest.mark.asyncio
    async def test_ping_returns_200_and_ok(self, test_app_client):
        """GET /ping returns 200 with {"status": "ok"}."""
        resp = await test_app_client.get("/ping")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )

        data = resp.json()
        assert data == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {data}"

        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, (
            f"Expected application/json, got: {content_type}"
        )

    @pytest.mark.asyncio
    async def test_ping_works_after_invocations(self, test_app_client):
        """GET /ping still works after using /invocations (no state corruption)."""
        # Call invocations first
        await test_app_client.post("/invocations", json={"message": "Hello"})

        # Then call ping
        resp = await test_app_client.get("/ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
# Scenario 7: Guard Mechanism — Structural Sensitivity Checks
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario7_GuardMechanism:
    """Verify tool sensitivity marking and write-operation positioning
    within the system prompt.  These tests check WHERE and HOW tools are
    marked, not just that the text exists (covered by Scenario 2).
    """

    SYSTEM_PROMPT: str

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        from app.agent_handler import SYSTEM_PROMPT
        self.SYSTEM_PROMPT = SYSTEM_PROMPT

    def test_send_email_in_write_safety_section(self):
        """send_email appears within the write operation safety section."""
        prompt = self.SYSTEM_PROMPT

        safety_start = prompt.find("写操作安全规则")
        assert safety_start >= 0, "Write safety section not found"

        safety_section = prompt[safety_start:]
        assert "send_email" in safety_section, (
            "send_email not found in write safety section"
        )

    def test_send_email_marked_as_sensitive(self):
        """send_email has a warning/restriction marker nearby."""
        prompt = self.SYSTEM_PROMPT

        safety_start = prompt.find("写操作安全规则")
        safety_section = prompt[safety_start:]

        assert "敏感" in safety_section or "禁止" in safety_section, (
            "send_email should be marked as sensitive/write operation"
        )

    def test_draft_reply_described_as_draft_only(self):
        """draft_reply is described as '只草拟不发送'."""
        prompt = self.SYSTEM_PROMPT

        assert "只草拟不发送" in prompt, (
            "Missing: draft_reply description '只草拟不发送'"
        )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 8: Email Tool Auth Decorator Configuration
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario8_EmailAuthConfig:
    """Verify email tool auth decorator parameters match specification."""

    def _read_source(self) -> str:
        """Read the email_tools.py source file."""
        email_tools_path = SERVICE_DIR / "app" / "tools" / "email_tools.py"
        return email_tools_path.read_text(encoding="utf-8")

    def test_list_emails_has_mail_read_scope(self):
        """list_emails uses scope Mail.Read with USER_FEDERATION."""
        source = self._read_source()

        assert 'Mail.Read' in source, (
            "Missing: Mail.Read scope in email_tools.py"
        )
        assert 'provider_name="m365-provider"' in source, (
            "Missing: provider_name=m365-provider"
        )
        assert 'auth_flow="USER_FEDERATION"' in source, (
            "Missing: auth_flow=USER_FEDERATION"
        )

    def test_get_email_has_mail_read_scope(self):
        """get_email uses scope Mail.Read."""
        source = self._read_source()
        read_count = source.count("Mail.Read")
        assert read_count >= 3, (
            f"Expected >=3 Mail.Read scopes (for list_emails, get_email, search_emails), "
            f"found {read_count}"
        )

    def test_search_emails_has_mail_read_scope(self):
        """search_emails uses scope Mail.Read."""
        source = self._read_source()
        search_idx = source.find("async def search_emails")
        assert search_idx > 0, "search_emails function not found in source"

        pre_context = source[:search_idx]
        assert "Mail.Read" in pre_context, (
            "Mail.Read scope not found before search_emails decorator"
        )

    def test_send_email_has_mail_send_scope(self):
        """send_email uses scope Mail.Send."""
        source = self._read_source()
        assert "Mail.Send" in source, (
            "Missing: Mail.Send scope in email_tools.py"
        )

    def test_draft_reply_has_mail_readwrite_scope(self):
        """draft_reply uses scope Mail.ReadWrite."""
        source = self._read_source()
        assert "Mail.ReadWrite" in source, (
            "Missing: Mail.ReadWrite scope in email_tools.py"
        )

    def test_all_email_tools_use_m365_provider(self):
        """All email tools use provider_name='m365-provider'."""
        source = self._read_source()
        m365_count = source.count('provider_name="m365-provider"')
        assert m365_count == 5, (
            f"Expected 5 email tools with m365-provider, found {m365_count}"
        )

    def test_all_email_tools_use_user_federation(self):
        """All email tools use auth_flow='USER_FEDERATION'."""
        source = self._read_source()
        uf_count = source.count('auth_flow="USER_FEDERATION"')
        assert uf_count == 5, (
            f"Expected 5 email tools with USER_FEDERATION, found {uf_count}"
        )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 9: OBS Tool Auth Decorator Configuration
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.feature
class TestScenario9_OBSAuthConfig:
    """Verify OBS tool auth decorator parameters match specification."""

    def _read_source(self) -> str:
        """Read the obs_tools.py source file."""
        obs_tools_path = SERVICE_DIR / "app" / "tools" / "obs_tools.py"
        return obs_tools_path.read_text(encoding="utf-8")

    def test_all_obs_tools_use_require_sts_token(self):
        """All 3 OBS tools use @require_sts_token decorator."""
        source = self._read_source()
        decorator_lines = [line for line in source.split("\n")
                           if line.strip().startswith("@require_sts_token")]
        assert len(decorator_lines) == 3, (
            f"Expected 3 @require_sts_token decorator lines, found {len(decorator_lines)}: "
            f"{decorator_lines}"
        )

    def test_obs_tools_use_provider_name(self):
        """All OBS tools specify a provider_name (from config or env)."""
        source = self._read_source()
        assert "provider_name=" in source, (
            "Missing: provider_name parameter in @require_sts_token decorator"
        )

    def test_obs_tools_use_agency_session_name(self):
        """All OBS tools specify agency_session_name."""
        source = self._read_source()
        assert "agency_session_name=" in source, (
            "Missing: agency_session_name parameter in @require_sts_token decorator"
        )

    def test_obs_config_loads_provider_name(self):
        """OBS config loading sets a provider name (non-empty)."""
        from app.tools.obs_tools import OBS_STS_PROVIDER_NAME

        assert OBS_STS_PROVIDER_NAME, "OBS_STS_PROVIDER_NAME should not be empty"
        assert isinstance(OBS_STS_PROVIDER_NAME, str), (
            f"OBS_STS_PROVIDER_NAME should be a string, got {type(OBS_STS_PROVIDER_NAME)}"
        )

    def test_obs_config_loads_endpoint(self):
        """OBS config loading sets an endpoint (non-empty)."""
        from app.tools.obs_tools import OBS_ENDPOINT

        assert OBS_ENDPOINT, "OBS_ENDPOINT should not be empty"
        assert isinstance(OBS_ENDPOINT, str), (
            f"OBS_ENDPOINT should be a string, got {type(OBS_ENDPOINT)}"
        )
        assert OBS_ENDPOINT.startswith("https://"), (
            f"OBS_ENDPOINT should start with https://, got {OBS_ENDPOINT}"
        )

    def test_obs_tools_not_using_user_federation(self):
        """OBS tools use @require_sts_token (not USER_FEDERATION for email)."""
        obs_source = self._read_source()
        assert "USER_FEDERATION" not in obs_source, (
            "OBS tools should use STS tokens, not USER_FEDERATION"
        )
