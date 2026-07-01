"""Regression test for bug-4: mount_chainlit relative path breaks import.

Related: personal-assistant-meta/issues/bugs/bug-4-cwd-sensitive-chainlit-mount/

`main.py` calls `mount_chainlit(target="app/playground.py")` with a relative path
that resolves against CWD. When importing `app.main` from outside SERVICE_DIR,
Chainlit's `check_file()` raises `BadParameter: File does not exist`.

When fixed: `from app.main import app` should succeed regardless of CWD.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure the service directory is on sys.path
SERVICE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "personal-assistant-service"
)


@pytest.fixture(autouse=True)
def ensure_service_on_path():
    """Ensure SERVICE_DIR is on sys.path for the duration of the test."""
    already_there = str(SERVICE_DIR) in sys.path
    if not already_there:
        sys.path.insert(0, str(SERVICE_DIR))
    yield
    if not already_there:
        sys.path.remove(str(SERVICE_DIR))


@pytest.mark.regression
class TestBug4CWDSensitiveChainlitMount:
    """Verify app.main can be imported regardless of CWD."""

    def test_import_app_main_from_project_root(self):
        """Import app.main from project root CWD after BUG-4 fix."""
        saved_cwd = os.getcwd()
        # Go to project root (two levels above SERVICE_DIR)
        project_root = SERVICE_DIR.parent
        try:
            os.chdir(str(project_root))
            # This should NOT raise BadParameter
            from app.main import app  # noqa: F401
        finally:
            os.chdir(saved_cwd)

    def test_import_app_main_from_service_dir(self):
        """Baseline: import app.main from SERVICE_DIR CWD — should always work."""
        saved_cwd = os.getcwd()
        try:
            os.chdir(str(SERVICE_DIR))
            from app.main import app  # noqa: F401
        finally:
            os.chdir(saved_cwd)
