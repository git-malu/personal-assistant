"""LLM Provider 配置加载模块。

读取项目根目录的 config.yaml，
暴露统一的 get_model(provider: str = None) -> BaseChatModel 接口。

本地 debug 可临时通过 provider 同名环境变量提供 API key；
生产环境通过 Agent Identity credential provider 获取 API key，避免在
Agent 代码或部署配置中保管模型密钥。
"""

import os
from pathlib import Path
from typing import Any

import yaml
from agentarts.sdk import IdentityClient
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.utils.constant import get_region
from langchain.chat_models import BaseChatModel, init_chat_model

from app.identity import MissingAgentIdentityTokenError

# 项目根目录 = app/llm_config.py 的上两级目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

# 缓存加载的配置，避免重复 I/O
_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """加载 config.yaml。若文件不存在则返回空 dict。"""
    global _config
    if _config is None:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
        else:
            _config = {}
    return _config


def _build_model(*, provider_config: dict[str, Any], api_key: str) -> BaseChatModel:
    return init_chat_model(
        model=f"openai:{provider_config['model']}",
        base_url=provider_config["base_url"],
        api_key=api_key,
    )


def _extract_api_key_value(api_key_result: Any) -> str | None:
    if api_key_result is None:
        return None
    if isinstance(api_key_result, str):
        return api_key_result.strip() or None
    for attr in ("api_key", "key", "value"):
        value = getattr(api_key_result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(api_key_result).strip() or None


def _resolve_llm_api_key(identity_provider_name: str) -> str:
    workload_access_token = AgentArtsRuntimeContext.get_workload_access_token()
    if not workload_access_token:
        raise MissingAgentIdentityTokenError("AgentArts workload access token is empty")

    client = IdentityClient(region=get_region())
    result = client.get_resource_api_key(
        provider_name=identity_provider_name,
        workload_access_token=workload_access_token,
    )
    api_key = _extract_api_key_value(result)
    if not api_key:
        raise MissingAgentIdentityTokenError(
            f"AgentArts returned an empty API key for {identity_provider_name}"
        )
    return api_key


def _get_provider_api_key(provider_name: str, provider_config: dict[str, Any]) -> str:
    identity_provider_name = provider_config.get("api_key_provider")
    if not identity_provider_name:
        raise ValueError(
            f"provider={provider_name} 未配置 api_key_provider。"
            " 请在 Agent Identity 中创建 API key provider，并在 config.yaml 中引用。"
        )

    local_debug_api_key = os.environ.get(identity_provider_name)
    if local_debug_api_key and local_debug_api_key.strip():
        return local_debug_api_key.strip()

    try:
        return _resolve_llm_api_key(identity_provider_name)
    except MissingAgentIdentityTokenError as e:
        raise ValueError(
            f"无法通过 Agent Identity 获取 provider={provider_name} 的 API key "
            f"({identity_provider_name}): {e}"
        ) from e


def get_model(provider: str | None = None) -> BaseChatModel:
    """获取 LLM model 实例。

    Args:
        provider: provider 名称（对应 config.yaml 中 llm.providers 下的 key）。
                  为 None 时使用 llm.default 指定的默认 provider。

    Returns:
        LangChain BaseChatModel 实例（OpenAI-compatible）。

    Raises:
        ValueError: 当配置缺失或 Agent Identity 无法提供 API key 时。
    """
    cfg = _load_config()
    llm_cfg = cfg.get("llm", {})

    if llm_cfg and "providers" in llm_cfg:
        # ── 正常路径：config.yaml 已配置 ──
        provider = provider or llm_cfg.get("default", "maas")
        providers = llm_cfg["providers"]
        p = providers.get(provider)
        if not p:
            raise ValueError(
                f"LLM provider '{provider}' 未在 config.yaml 中配置。"
                f" 可用 providers: {list(providers.keys())}"
            )
        api_key = _get_provider_api_key(provider, p)
        return _build_model(provider_config=p, api_key=api_key)
    raise ValueError(
        "config.yaml 未配置 llm providers。"
        " 请在 config.yaml 配置 llm.providers.*.api_key_provider，"
        "并在 Agent Identity 中创建对应 API key provider。"
    )
