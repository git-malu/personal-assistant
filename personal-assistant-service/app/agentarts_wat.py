"""Helpers for AgentArts Workload Access Token exchange."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from agentarts.sdk import IdentityClient
from agentarts.sdk.utils.constant import get_region

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
_AGENTARTS_CONFIG_PATH = _SERVICE_ROOT / ".agentarts_config.yaml"


@lru_cache
def get_workload_name(config_path: Path = _AGENTARTS_CONFIG_PATH) -> str:
    """Return the configured AgentArts workload identity name."""
    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    default_agent = config.get("default_agent")
    agents = config.get("agents") or {}
    agent_config = agents.get(default_agent) if default_agent else None
    if not agent_config and agents:
        agent_config = next(iter(agents.values()))

    workload_name = ((agent_config or {}).get("base") or {}).get("name")
    if not isinstance(workload_name, str) or not workload_name.strip():
        raise RuntimeError("AgentArts workload name is not configured")
    return workload_name.strip()


def create_jwt_mode_workload_access_token(
    user_token: str,
    *,
    client: IdentityClient | None = None,
    workload_name: str | None = None,
) -> str:
    """Exchange an inbound user JWT for a JWT-mode Workload Access Token."""
    token = user_token.strip()
    if not token:
        raise ValueError("user_token must not be empty")

    identity_client = client or IdentityClient(region=get_region())
    resolved_workload_name = workload_name or get_workload_name()
    return identity_client.create_workload_access_token(
        resolved_workload_name,
        user_token=token,
    )
