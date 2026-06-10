"""E2E test fixtures for personal-assistant service + client integration.

Provides shared fixtures for managing service lifecycle, HTTP clients,
and environment configuration across E2E test scenarios.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CONFIG_YAML = SERVICE_DIR / "config.yaml"
CONFIG_YAML_BACKUP = SERVICE_DIR / "config.yaml.e2e-backup"

# Add service directory to sys.path so that `from app.main import app` works
# when pytest is invoked from the e2e directory or project root.
_SERVICE_SRC = str(SERVICE_DIR)
if _SERVICE_SRC not in sys.path:
    sys.path.insert(0, _SERVICE_SRC)


def _get_uv_path() -> str:
    """Get the uv binary path from the service's virtual environment."""
    uv_path = SERVICE_DIR / ".venv" / "bin" / "uv"
    if uv_path.exists():
        return str(uv_path)
    return "uv"


@pytest.fixture(scope="session")
def service_venv_python() -> str:
    """Return path to the Python interpreter in the service's venv."""
    python_path = SERVICE_DIR / ".venv" / "bin" / "python"
    if python_path.exists():
        return str(python_path)
    return sys.executable


# ── Config file management ─────────────────────────────────────────────
# NOTE: Config backup/restore is handled by the test file's manage_config
# fixture. This conftest fixture is intentionally removed to avoid conflicts.


# ── TestClient-based E2E fixtures ─────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """Clear all LLM-related environment variables to ensure clean state."""
    llm_vars = [
        "MAAS_API_KEY",
        "DEEPSEEK_API_KEY",
        "MODEL_API_KEY",
        "MODEL_NAME",
        "MODEL_URL",
    ]
    for var in llm_vars:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def e2e_client(clean_env):
    """Create a FastAPI TestClient with mocked LLM.

    This fixture:
    1. Sets up required environment variables for the test scenario
    2. Mocks init_chat_model to avoid real API calls
    3. Returns a TestClient that exercises the full FastAPI stack
    """
    from unittest.mock import MagicMock, patch

    # Default: mock init_chat_model to return a dummy model
    # Individual tests can override env vars before creating the client
    with patch(
        "app.llm_config.init_chat_model", return_value=MagicMock()
    ) as mock_init:
        from app.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_init


# ── Subprocess-based service fixture (for true process-level E2E) ────


class ServiceProcess:
    """Manage a subprocess running the uvicorn server."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, env: dict[str, str] | None = None, timeout: float = 60.0):
        """Start the service in a subprocess."""
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        self.process = subprocess.Popen(
            [
                _get_uv_path(),
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "error",
            ],
            cwd=str(SERVICE_DIR),
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for health check or error
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                # Process exited — collect stderr for diagnostics
                _, stderr = self.process.communicate(timeout=5)
                raise RuntimeError(
                    f"Service exited with code {self.process.returncode}: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
            try:
                resp = httpx.get(f"{self.url}/ping", timeout=2.0)
                if resp.status_code == 200:
                    return  # Success
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(
            f"Service did not become healthy within {timeout}s on port {self.port}"
        )

    def stop(self):
        """Stop the service subprocess."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None

    def get_stderr(self) -> str:
        """Read any stderr output from the process."""
        if self.process and self.process.stderr:
            try:
                stderr_bytes = self.process.stderr.read()
                return stderr_bytes.decode(errors="replace")
            except Exception:
                return ""
        return ""


@pytest.fixture
def service_process():
    """Fixture that yields a ServiceProcess manager."""
    sp = ServiceProcess()
    yield sp
    sp.stop()


@pytest.fixture
def e2e_http_client():
    """Async httpx client for real HTTP E2E tests."""
    client = httpx.Client(timeout=10.0)
    yield client
    client.close()
