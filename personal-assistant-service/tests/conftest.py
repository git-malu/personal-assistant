"""pytest configuration — mock external SDKs before any test imports.

AgentArts SDK and Huawei OBS SDK are not available in test environments.
We inject mock modules via sys.modules BEFORE any test module is imported.
"""

import sys
from unittest.mock import MagicMock


def pytest_configure(config):  # noqa: ARG001
    """Inject mock modules before test collection starts.

    This runs before pytest imports any test file, so when app.tools.*
    modules are first imported, they get our mock agentarts.sdk instead
    of the real one.
    """
    # ── mock agentarts SDK ──────────────────────────────────────────────
    if "agentarts" not in sys.modules:
        sys.modules["agentarts"] = MagicMock()
    if "agentarts.sdk" not in sys.modules:
        _mock_sdk = MagicMock()
        # require_access_token: no-op decorator that returns identity wrapper
        _mock_sdk.require_access_token = MagicMock(
            side_effect=lambda **kw: lambda f: f
        )
        # require_sts_token: no-op decorator that returns identity wrapper
        _mock_sdk.require_sts_token = MagicMock(
            side_effect=lambda **kw: lambda f: f
        )
        sys.modules["agentarts.sdk"] = _mock_sdk
    if "agentarts.sdk.identity" not in sys.modules:
        _mock_identity = MagicMock()
        _mock_identity.OAuth2Vendor = MagicMock()
        _mock_identity.IdentityClient = MagicMock()
        sys.modules["agentarts.sdk.identity"] = _mock_identity

    # ── mock azure.identity (local dev fallback) ────────────────────────
    if "azure" not in sys.modules:
        sys.modules["azure"] = MagicMock()
    if "azure.identity" not in sys.modules:
        _mock_azure_id = MagicMock()
        # DeviceCodeCredential — used in local dev when access_token is None
        _mock_azure_id.DeviceCodeCredential = MagicMock()
        sys.modules["azure.identity"] = _mock_azure_id

    # ── mock esdk-obs-python (imported as "obs") ────────────────────────
    if "obs" not in sys.modules:
        _mock_obs = MagicMock()
        sys.modules["obs"] = _mock_obs
