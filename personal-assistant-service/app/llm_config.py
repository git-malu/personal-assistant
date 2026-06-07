"""LLM Provider 配置加载模块。

读取项目根目录的 config.yaml + 环境变量，
暴露统一的 get_model(provider: str = None) -> BaseChatModel 接口。

当 config.yaml 不存在时，fallback 到旧版环境变量：
  MODEL_URL / MODEL_API_KEY / MODEL_NAME
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from langchain.chat_models import BaseChatModel, init_chat_model

logger = logging.getLogger(__name__)

# 项目根目录 = app/llm_config.py 的上两级目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

# 缓存加载的配置，避免重复 I/O
_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """加载 config.yaml。若文件不存在则返回空 dict（触发 fallback）。"""
    global _config
    if _config is None:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                _config = yaml.safe_load(f)
        else:
            _config = {}  # 空配置 → 触发 fallback 逻辑
    return _config


def get_model(provider: str | None = None) -> BaseChatModel:
    """获取 LLM model 实例。

    Args:
        provider: provider 名称（对应 config.yaml 中 llm.providers 下的 key）。
                  为 None 时使用 llm.default 指定的默认 provider。
                  当 config.yaml 不存在或未配置对应 provider 时，
                  自动 fallback 到 MODEL_URL / MODEL_API_KEY / MODEL_NAME 环境变量。

    Returns:
        LangChain BaseChatModel 实例（OpenAI-compatible）。

    Raises:
        ValueError: 当必填的 api_key 环境变量未设置时。
    """
    cfg = _load_config()
    llm_cfg = cfg.get("llm", {})

    if llm_cfg and "providers" in llm_cfg:
        # ── 正常路径：config.yaml 已配置 ──
        is_default = provider is None
        provider = provider or llm_cfg.get("default", "maas")
        providers = llm_cfg["providers"]
        p = providers.get(provider)
        if not p:
            raise ValueError(
                f"LLM provider '{provider}' 未在 config.yaml 中配置。"
                f" 可用 providers: {list(providers.keys())}"
            )
        api_key = os.environ.get(p["api_key_env"])
        if api_key:
            return init_chat_model(
                model=f"openai:{p['model']}",
                base_url=p["base_url"],
                api_key=api_key,
            )
        # 仅一个 provider 时保持原有快速失败行为，提供精确的 env var 名称
        if len(providers) == 1:
            raise ValueError(
                f"环境变量 {p['api_key_env']} 未设置，provider={provider} 不可用。"
                f" 请设置 {p['api_key_env']} 环境变量后重试。"
            )
        # 多个 provider：扫描其他 provider 作为 fallback
        logger.warning(
            f"Default provider '{provider}' API key ({p['api_key_env']}) not set, "
            f"scanning alternatives..."
        )
        for alt_name, alt_p in providers.items():
            if alt_name == provider:
                continue
            alt_key = os.environ.get(alt_p["api_key_env"])
            if alt_key:
                request_label = "default" if is_default else "requested"
                logger.warning(
                    f"Auto-falling back to provider '{alt_name}'. "
                    f"To use the {request_label} provider '{provider}', "
                    f"set {p['api_key_env']} env var, "
                    f"or change llm.default to '{alt_name}' in config.yaml."
                )
                return init_chat_model(
                    model=f"openai:{alt_p['model']}",
                    base_url=alt_p["base_url"],
                    api_key=alt_key,
                )
        raise ValueError(
            f"没有可用的 LLM provider。已检查 providers: {list(providers.keys())}。"
            f" 请设置任一 provider 的 API key 环境变量后重试。"
        )
    else:
        # ── Fallback 路径：config.yaml 不存在或未配置 llm section ──
        model_url = os.environ.get(
            "MODEL_URL", "https://api.modelarts-maas.com/openai/v1"
        )
        model_api_key = os.environ.get("MODEL_API_KEY")
        model_name = os.environ.get("MODEL_NAME", "deepseek-v4-pro")

        if not model_api_key:
            raise ValueError(
                "config.yaml 未配置且 MODEL_API_KEY 环境变量未设置。"
                " 请创建 config.yaml 或设置 MODEL_API_KEY 环境变量。"
            )
        return init_chat_model(
            model=f"openai:{model_name}",
            base_url=model_url,
            api_key=model_api_key,
        )
