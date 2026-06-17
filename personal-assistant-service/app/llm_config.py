"""LLM provider configuration and AgentArts Identity credential loading.

Caching strategy: LLM API Keys are fetched once from AgentArts Identity SDK
(@require_api_key decorator) per container lifecycle and cached in a
module-level _API_KEY_CACHE dict + os.environ. Subsequent get_model() calls
return cached keys with zero IPC overhead. Key rotation is handled by
container restart (agentarts launch), which naturally clears all caches.
See ADR-016 + Refactor 8 for design rationale.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from agentarts.sdk import require_api_key
from langchain.chat_models import BaseChatModel, init_chat_model

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

_config: dict[str, Any] | None = None

# 进程级 API Key 缓存，避免每次 get_model() 都触发 SDK IPC 调用
# Key: credential_provider_name (如 "DEEPSEEK_API_KEY")
# Value: 从 AgentArts Identity 获取的明文 API Key
# 设计依据: ADR-016 § "AgentArts Identity + 进程级缓存"
# 生命周期: 与容器进程一致；Key 轮转通过 agentarts launch 重建容器完成
_API_KEY_CACHE: dict[str, str] = {}


def _load_config() -> dict[str, Any]:
    """Load config.yaml once and cache it."""
    global _config
    if _config is None:
        if not _CONFIG_PATH.exists():
            raise ValueError(
                "config.yaml is required for LLM provider configuration. "
                "LLM API keys must be stored in AgentArts Identity providers."
            )
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
    return _config


def _resolve_provider(provider: str | None = None) -> tuple[str, dict[str, Any]]:
    cfg = _load_config()
    llm_cfg = cfg.get("llm")
    if not isinstance(llm_cfg, dict):
        raise ValueError("config.yaml must define an llm section.")

    providers = llm_cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("config.yaml must define llm.providers.")

    provider_name = provider or llm_cfg.get("default")
    if not provider_name:
        raise ValueError("config.yaml must define llm.default.")

    provider_cfg = providers.get(provider_name)
    if not isinstance(provider_cfg, dict):
        raise ValueError(
            f"LLM provider '{provider_name}' is not configured. "
            f"Available providers: {list(providers.keys())}"
        )

    missing = [
        key
        for key in ("base_url", "model", "credential_provider_name")
        if not provider_cfg.get(key)
    ]
    if missing:
        raise ValueError(
            f"LLM provider '{provider_name}' is missing required fields: {missing}."
        )

    return provider_name, provider_cfg


def validate_model_config(provider: str | None = None) -> None:
    """Validate provider metadata without fetching secrets from AgentArts Identity."""
    _resolve_provider(provider)


def _resolve_model_endpoint(provider_cfg: dict[str, Any]) -> tuple[str, str]:
    """Resolve non-secret model metadata with optional env overrides."""
    model = os.environ.get("MODEL_NAME") or provider_cfg["model"]
    base_url = os.environ.get("MODEL_URL") or provider_cfg["base_url"]
    return model, base_url


def _get_api_key_from_identity(credential_provider_name: str) -> str:
    """Fetch an API key from AgentArts Identity via the SDK decorator.

    Performs process-level caching: first retrieval goes through the SDK
    (AgentArts Identity IPC, ~10-50ms), subsequent calls read the cached
    value from _API_KEY_CACHE or os.environ (zero IPC overhead).

    Cache tiers (checked in order):
      1. _API_KEY_CACHE — module-level explicit cache (fastest)
      2. os.environ — supports external injection / test fixture presets
      3. @require_api_key SDK — AgentArts Identity Service IPC

    Multi-provider isolation: each provider_name has its own cache entry.
    Key rotation requires container restart (consistent with current ops).
    """
    # 1. Check process-level cache (fastest path)
    cached = _API_KEY_CACHE.get(credential_provider_name)
    if cached:
        return cached

    # 2. Check os.environ — supports external injection (e.g. test fixtures,
    #    subprocess visibility, operator debugging)
    env_key = os.environ.get(credential_provider_name)
    if env_key:
        _API_KEY_CACHE[credential_provider_name] = env_key
        return env_key

    # 3. Cache miss → fetch from AgentArts Identity via SDK
    @require_api_key(provider_name=credential_provider_name, into="api_key")
    def _fetch(api_key: str | None = None) -> str:
        if not api_key:
            raise ValueError(
                f"AgentArts Identity provider '{credential_provider_name}' "
                "returned an empty API key."
            )
        return api_key

    api_key = _fetch()

    # 4. Populate both cache layers for subsequent zero-IPC access
    _API_KEY_CACHE[credential_provider_name] = api_key
    os.environ[credential_provider_name] = api_key

    return api_key


def get_model(provider: str | None = None) -> BaseChatModel:
    """Build an OpenAI-compatible LangChain model using an SDK-managed API key."""
    _, provider_cfg = _resolve_provider(provider)
    api_key = _get_api_key_from_identity(provider_cfg["credential_provider_name"])
    model, base_url = _resolve_model_endpoint(provider_cfg)
    return init_chat_model(
        model=f"openai:{model}",
        base_url=base_url,
        api_key=api_key,
    )
