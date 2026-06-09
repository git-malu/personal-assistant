"""华为云 OBS 对象存储工具函数。

提供 3 个异步 OBS 工具，通过双路径 auth 支持：
- Production: @require_sts_token 装饰器注入 STS 临时凭证
- Local Dev: 环境变量 OBS_ACCESS_KEY_ID / OBS_SECRET_ACCESS_KEY fallback

所有函数返回结构化 dict，错误信息包含在返回 dict 中，不抛出异常。
"""

import asyncio
import contextlib
import json
import os
from pathlib import Path

import yaml
from agentarts.sdk import require_sts_token

# ---------------------------------------------------------------------------
# Module-level config loading
# ---------------------------------------------------------------------------


def _load_obs_config():
    """Load OBS config: env vars > config.yaml > hardcoded defaults.

    Returns:
        Tuple of (endpoint, sts_provider_name).
    """
    endpoint = os.environ.get("OBS_ENDPOINT")
    sts_provider = os.environ.get("OBS_STS_PROVIDER_NAME")

    if not endpoint or not sts_provider:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            obs_cfg = cfg.get("obs", {})
            if not endpoint:
                endpoint = obs_cfg.get("endpoint")
            if not sts_provider:
                sts_provider = obs_cfg.get("sts_provider_name")

    if not endpoint:
        endpoint = "https://obs.cn-southwest-2.myhuaweicloud.com"
    if not sts_provider:
        raise RuntimeError(
            "STS provider name not configured. Set OBS_STS_PROVIDER_NAME env var "
            "or obs.sts_provider_name in config.yaml"
        )

    return endpoint, sts_provider


OBS_ENDPOINT, OBS_STS_PROVIDER_NAME = _load_obs_config()

# ---------------------------------------------------------------------------
# Content type detection
# ---------------------------------------------------------------------------

_TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".yaml", ".yml", ".log"}


def _is_text_file(key: str) -> bool:
    """Determine if a file key has a text-readable extension."""
    ext = Path(key).suffix.lower()
    return ext in _TEXT_EXTENSIONS or ext == ".json"


def _is_json_file(key: str) -> bool:
    """Determine if a file key is a JSON file."""
    return Path(key).suffix.lower() == ".json"


# ---------------------------------------------------------------------------
# ObsClient factory
# ---------------------------------------------------------------------------


def _make_obs_client(
    sts_credentials,
) -> "ObsClient":  # type: ignore[name-defined] # noqa: F821
    """Create an ObsClient instance from sts_credentials or env vars.

    Production: sts_credentials is injected by @require_sts_token decorator.
    Local Dev: sts_credentials is None, fallback to OBS_ACCESS_KEY_ID /
    OBS_SECRET_ACCESS_KEY env vars.
    """
    from obs import ObsClient

    if sts_credentials is not None:
        return ObsClient(
            access_key_id=sts_credentials.access_key_id,
            secret_access_key=sts_credentials.secret_access_key,
            security_token=sts_credentials.security_token,
            server=OBS_ENDPOINT,
        )
    # Local dev: use AK/SK from env (no security token)
    ak = os.environ.get("OBS_ACCESS_KEY_ID")
    sk = os.environ.get("OBS_SECRET_ACCESS_KEY")
    if not ak or not sk:
        raise RuntimeError(
            "OBS credentials not available. Set OBS_ACCESS_KEY_ID and "
            "OBS_SECRET_ACCESS_KEY env vars for local dev, or deploy on "
            "AgentArts Runtime for STS token injection."
        )
    return ObsClient(access_key_id=ak, secret_access_key=sk, server=OBS_ENDPOINT)


# ---------------------------------------------------------------------------
# list_obs_objects
# ---------------------------------------------------------------------------


@require_sts_token(
    provider_name=OBS_STS_PROVIDER_NAME,
    agency_session_name="personal-assistant-obs-session",
)
async def list_obs_objects(
    bucket: str,
    prefix: str = "",
    limit: int = 100,
    sts_credentials=None,
) -> dict:
    """列出指定 OBS Bucket 中某个 prefix 下的对象。

    Args:
        bucket: OBS Bucket 名称。
        prefix: 对象键前缀（目录），例如 "logs/"。
        limit: 返回数量上限，默认 100。
        sts_credentials: STS 临时凭证（Production 由装饰器注入）。
                         Local Dev 传入 None 时使用 OBS_ACCESS_KEY_ID /
                         OBS_SECRET_ACCESS_KEY 环境变量。

    Returns:
        dict: {"bucket", "prefix", "objects": [{"key", "size", "last_modified"}, ...],
               "truncated": bool}
    """
    try:
        obs_client = _make_obs_client(sts_credentials)
        resp = await asyncio.to_thread(
            obs_client.listObjects, bucket, prefix=prefix, max_keys=limit
        )
        contents = resp.body.contents if resp.body.contents else []
        objects = [
            {
                "key": obj.key,
                "size": obj.size,
                "last_modified": obj.lastModified,
            }
            for obj in contents
        ]
        return {
            "bucket": bucket,
            "prefix": prefix,
            "objects": objects,
            "truncated": resp.body.isTruncated
            if hasattr(resp.body, "isTruncated")
            else len(contents) >= limit,
        }
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "get_error_code"):
            with contextlib.suppress(Exception):
                error_msg = f"{e.get_error_code()}: {e.get_error_message()}"
        return {"error": error_msg, "bucket": bucket, "prefix": prefix}


# ---------------------------------------------------------------------------
# get_obs_object
# ---------------------------------------------------------------------------


@require_sts_token(
    provider_name=OBS_STS_PROVIDER_NAME,
    agency_session_name="personal-assistant-obs-session",
)
async def get_obs_object(
    bucket: str, key: str, sts_credentials=None
) -> dict:
    """读取 OBS 对象的完整内容。

    自动检测文件类型：JSON 文件解析并格式化返回；文本文件直接返回；
    二进制文件返回元数据信息。

    单文件读取上限 1MB，超大文件会截断并标记 truncated=true。

    Args:
        bucket: OBS Bucket 名称。
        key: 对象键（完整路径）。
        sts_credentials: STS 临时凭证（Production 由装饰器注入）。

    Returns:
        dict: {"bucket", "key", "content_type", "content", "size", "truncated"}
    """
    try:
        obs_client = _make_obs_client(sts_credentials)
        resp = await asyncio.to_thread(obs_client.getObject, bucket, key)
        raw_bytes = resp.body.buffer if hasattr(resp.body, "buffer") else resp.body
        total_size = len(raw_bytes) if raw_bytes else 0

        truncated = False
        if total_size > 1024 * 1024:  # 1MB limit
            raw_bytes = raw_bytes[: 1024 * 1024]
            truncated = True

        content_type = "binary"
        content = None

        if _is_json_file(key):
            content_type = "json"
            if raw_bytes:
                try:
                    parsed = json.loads(raw_bytes.decode("utf-8"))
                    content = json.dumps(parsed, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Corrupt JSON or not actually JSON — treat as text
                    content = raw_bytes.decode("utf-8", errors="replace")
                    content_type = "text"
        elif _is_text_file(key):
            content_type = "text"
            if raw_bytes:
                content = raw_bytes.decode("utf-8", errors="replace")
        else:
            # Binary file
            content = None
            content_type = "binary"

        return {
            "bucket": bucket,
            "key": key,
            "content_type": content_type,
            "content": content,
            "size": total_size,
            "truncated": truncated,
            "note": "二进制文件，无法以文本形式展示"
            if content_type == "binary"
            else None,
        }
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "get_error_code"):
            with contextlib.suppress(Exception):
                error_msg = f"{e.get_error_code()}: {e.get_error_message()}"
        return {"error": error_msg, "bucket": bucket, "key": key}


# ---------------------------------------------------------------------------
# get_obs_object_metadata
# ---------------------------------------------------------------------------


@require_sts_token(
    provider_name=OBS_STS_PROVIDER_NAME,
    agency_session_name="personal-assistant-obs-session",
)
async def get_obs_object_metadata(
    bucket: str, key: str, sts_credentials=None
) -> dict:
    """查询 OBS 对象的元数据（不读取内容）。

    Args:
        bucket: OBS Bucket 名称。
        key: 对象键（完整路径）。
        sts_credentials: STS 临时凭证（Production 由装饰器注入）。

    Returns:
        dict: {"bucket", "key", "content_type", "size", "last_modified", "etag"}
    """
    try:
        obs_client = _make_obs_client(sts_credentials)
        resp = await asyncio.to_thread(obs_client.getObjectMetadata, bucket, key)
        body = resp.body
        return {
            "bucket": bucket,
            "key": key,
            "content_type": getattr(body, "contentType", None),
            "size": getattr(body, "contentLength", None),
            "last_modified": getattr(body, "lastModified", None),
            "etag": getattr(body, "etag", None),
        }
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "get_error_code"):
            with contextlib.suppress(Exception):
                error_msg = f"{e.get_error_code()}: {e.get_error_message()}"
        return {"error": error_msg, "bucket": bucket, "key": key}
