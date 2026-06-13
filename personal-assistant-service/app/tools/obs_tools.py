import asyncio
import os
from typing import Annotated

from agentarts.sdk import require_sts_token
from langchain_core.tools import InjectedToolArg, tool
from obs import ObsClient
from obs.model import GetObjectHeader

OBS_PROVIDER_NAME = "huaweicloud-sts-provider"
OBS_AGENCY_SESSION_NAME = "personal-assistant-obs-session"
OBS_ENDPOINT_ENV = "OBS_ENDPOINT"
DEFAULT_OBS_ENDPOINT = "https://obs.cn-southwest-2.myhuaweicloud.com"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_MAX_READ_BYTES = 1024 * 1024
MAX_READ_BYTES = 5 * 1024 * 1024

TEXT_CONTENT_TYPES = (
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "text/",
)
TEXT_EXTENSIONS = (
    ".csv",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".properties",
    ".text",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
)


class OBSToolError(RuntimeError):
    """Raised when OBS returns an error that should be visible to the agent."""


def _normalize_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def _normalize_max_bytes(max_bytes: int) -> int:
    return max(1, min(max_bytes, MAX_READ_BYTES))


def _obs_endpoint() -> str:
    return os.environ.get(OBS_ENDPOINT_ENV, DEFAULT_OBS_ENDPOINT)


def _require_sts_credentials(sts_credentials) -> None:
    if not sts_credentials:
        raise OBSToolError(
            "Missing Huawei Cloud STS credentials from AgentArts Identity."
        )
    for attr in ("access_key_id", "secret_access_key", "security_token"):
        if not getattr(sts_credentials, attr, None):
            raise OBSToolError(f"Missing STS credential field: {attr}.")


def _create_obs_client(sts_credentials) -> ObsClient:
    _require_sts_credentials(sts_credentials)
    return ObsClient(
        access_key_id=sts_credentials.access_key_id,
        secret_access_key=sts_credentials.secret_access_key,
        security_token=sts_credentials.security_token,
        server=_obs_endpoint(),
    )


def _raise_for_obs_error(
    response,
    action: str,
    bucket: str,
    key: str | None = None,
) -> None:
    status = getattr(response, "status", None)
    if status is not None and status < 300:
        return

    target = f"{bucket}/{key}" if key else bucket
    messages = {
        401: (
            "OBS authorization failed. Check the AgentArts STS provider "
            "and IAM agency."
        ),
        403: (
            "OBS denied this request. Check read permission for the requested "
            "bucket/object."
        ),
        404: f"OBS target was not found: {target}.",
    }
    default = f"OBS {action} failed"
    if status:
        default = f"{default} with status {status}"

    detail = getattr(response, "errorMessage", None) or getattr(
        response, "reason", None
    )
    code = getattr(response, "errorCode", None)
    message = messages.get(status, default)
    if code:
        message = f"{message} Code: {code}."
    if detail:
        message = f"{message} Detail: {detail}"
    raise OBSToolError(message)


def _header_dict(response) -> dict[str, str]:
    headers = getattr(response, "header", None) or []
    result = {}
    for item in headers:
        if isinstance(item, tuple) and len(item) == 2:
            result[str(item[0]).lower()] = str(item[1])
    return result


def _metadata_from_response(bucket: str, key: str, response) -> dict:
    body = getattr(response, "body", None)
    headers = _header_dict(response)
    metadata = {
        name[11:]: value
        for name, value in headers.items()
        if name.startswith("x-obs-meta-") or name.startswith("x-amz-meta-")
    }
    return {
        "bucket": bucket,
        "key": key,
        "size": getattr(body, "contentLength", None),
        "content_type": getattr(body, "contentType", None),
        "last_modified": getattr(body, "lastModified", None),
        "etag": getattr(body, "etag", None),
        "storage_class": getattr(body, "storageClass", None),
        "metadata": metadata,
    }


def _object_summary(bucket: str, item) -> dict:
    return {
        "bucket": bucket,
        "key": getattr(item, "key", None),
        "size": getattr(item, "size", None),
        "last_modified": getattr(item, "lastModified", None),
        "etag": getattr(item, "etag", None),
        "storage_class": getattr(item, "storageClass", None),
    }


def _is_text_object(key: str, content_type: str | None) -> bool:
    normalized_type = (content_type or "").lower()
    if any(normalized_type.startswith(prefix) for prefix in TEXT_CONTENT_TYPES):
        return True
    lower_key = key.lower()
    return any(lower_key.endswith(extension) for extension in TEXT_EXTENSIONS)


def _read_response_bytes(response) -> bytes:
    body = getattr(response, "body", None)
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")

    response_value = getattr(body, "response", None)
    if isinstance(response_value, bytes):
        return response_value
    if isinstance(response_value, str):
        return response_value.encode("utf-8")

    for method_name in ("read",):
        method = getattr(body, method_name, None)
        if callable(method):
            data = method()
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return data.encode("utf-8")
    return bytes(body) if isinstance(body, bytearray) else b""


def fetch_obs_objects(
    *,
    bucket: str,
    prefix: str = "",
    limit: int = DEFAULT_LIMIT,
    sts_credentials=None,
) -> list[dict]:
    client = _create_obs_client(sts_credentials)
    per_page = _normalize_limit(limit)
    response = client.listObjects(bucket, prefix=prefix or None, max_keys=per_page)
    _raise_for_obs_error(response, "list objects", bucket)

    body = getattr(response, "body", None)
    contents = getattr(body, "contents", None) or []
    return [_object_summary(bucket, item) for item in contents[:per_page]]


def fetch_obs_object_metadata(
    *,
    bucket: str,
    key: str,
    sts_credentials=None,
) -> dict:
    client = _create_obs_client(sts_credentials)
    response = client.getObjectMetadata(bucket, key)
    _raise_for_obs_error(response, "get object metadata", bucket, key)
    return _metadata_from_response(bucket, key, response)


def fetch_obs_text_object(
    *,
    bucket: str,
    key: str,
    max_bytes: int = DEFAULT_MAX_READ_BYTES,
    sts_credentials=None,
) -> dict:
    client = _create_obs_client(sts_credentials)
    byte_limit = _normalize_max_bytes(max_bytes)

    metadata_response = client.getObjectMetadata(bucket, key)
    _raise_for_obs_error(metadata_response, "get object metadata", bucket, key)
    metadata = _metadata_from_response(bucket, key, metadata_response)

    if not _is_text_object(key, metadata.get("content_type")):
        raise OBSToolError(
            f"OBS object {bucket}/{key} does not look like a text file. "
            "Use metadata first, or request a text/JSON/CSV/log object."
        )

    content_length = metadata.get("size")
    truncated = bool(content_length is not None and int(content_length) > byte_limit)
    headers = GetObjectHeader(range=f"bytes=0-{byte_limit - 1}")
    response = client.getObject(bucket, key, headers=headers, loadStreamInMemory=True)
    _raise_for_obs_error(response, "read object", bucket, key)

    raw = _read_response_bytes(response)[:byte_limit]
    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replace"

    return {
        **metadata,
        "content": content,
        "truncated": truncated,
        "encoding": encoding,
        "bytes_read": len(raw),
    }


async def _list_obs_objects_impl(
    bucket: str,
    prefix: str = "",
    limit: int = DEFAULT_LIMIT,
    sts_credentials: Annotated[object | None, InjectedToolArg] = None,
) -> list[dict]:
    """List objects in a Huawei Cloud OBS bucket using AgentArts STS credentials."""
    return await asyncio.to_thread(
        fetch_obs_objects,
        bucket=bucket,
        prefix=prefix,
        limit=limit,
        sts_credentials=sts_credentials,
    )


async def _get_obs_object_metadata_impl(
    bucket: str,
    key: str,
    sts_credentials: Annotated[object | None, InjectedToolArg] = None,
) -> dict:
    """Get metadata for a Huawei Cloud OBS object using AgentArts STS credentials."""
    return await asyncio.to_thread(
        fetch_obs_object_metadata,
        bucket=bucket,
        key=key,
        sts_credentials=sts_credentials,
    )


async def _read_obs_text_object_impl(
    bucket: str,
    key: str,
    max_bytes: int = DEFAULT_MAX_READ_BYTES,
    sts_credentials: Annotated[object | None, InjectedToolArg] = None,
) -> dict:
    """Read a text-like Huawei Cloud OBS object using AgentArts STS credentials."""
    return await asyncio.to_thread(
        fetch_obs_text_object,
        bucket=bucket,
        key=key,
        max_bytes=max_bytes,
        sts_credentials=sts_credentials,
    )


list_obs_objects = tool(
    "list_obs_objects",
    description="List objects in a Huawei Cloud OBS bucket by bucket and prefix.",
)(
    require_sts_token(
        provider_name=OBS_PROVIDER_NAME,
        agency_session_name=OBS_AGENCY_SESSION_NAME,
    )(_list_obs_objects_impl)
)
get_obs_object_metadata = tool(
    "get_obs_object_metadata",
    description="Get metadata for a Huawei Cloud OBS object by bucket and key.",
)(
    require_sts_token(
        provider_name=OBS_PROVIDER_NAME,
        agency_session_name=OBS_AGENCY_SESSION_NAME,
    )(_get_obs_object_metadata_impl)
)
read_obs_text_object = tool(
    "read_obs_text_object",
    description=(
        "Read a text, JSON, CSV, log, markdown, XML, or YAML object "
        "from Huawei Cloud OBS."
    ),
)(
    require_sts_token(
        provider_name=OBS_PROVIDER_NAME,
        agency_session_name=OBS_AGENCY_SESSION_NAME,
    )(_read_obs_text_object_impl)
)

OBS_TOOLS = [list_obs_objects, get_obs_object_metadata, read_obs_text_object]
