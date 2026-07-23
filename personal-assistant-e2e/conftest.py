"""E2E test fixtures for personal-assistant service + client integration.

Provides shared fixtures for managing service lifecycle, HTTP clients,
and environment configuration across E2E test scenarios.
"""

import contextlib
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
SERVICE_RUNNER = Path(__file__).resolve().parent / "scripts" / "run_service.py"


def _get_uv_path() -> str:
    """Get the uv binary path from the service's virtual environment."""
    uv_path = SERVICE_DIR / ".venv" / "bin" / "uv"
    if uv_path.exists():
        return str(uv_path)
    return "uv"


def terminate_process_tree(process: subprocess.Popen, timeout: float = 10.0) -> None:
    """Terminate a subprocess and its children."""
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=timeout)
        return

    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
                "python",
                str(SERVICE_RUNNER),
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
            terminate_process_tree(self.process)
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
