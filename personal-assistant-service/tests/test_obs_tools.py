"""Unit tests for Huawei Cloud OBS AgentArts Identity tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.tools.obs_tools import (
    DEFAULT_OBS_ENDPOINT,
    OBSToolError,
    _list_obs_objects_impl,
    fetch_obs_object_metadata,
    fetch_obs_objects,
    fetch_obs_text_object,
    get_obs_object_metadata,
    list_obs_objects,
    read_obs_text_object,
)


def _sts():
    return SimpleNamespace(
        access_key_id="ak",
        secret_access_key="sk",
        security_token="token",
        expiration="2026-06-13T12:00:00Z",
    )


def _response(status=200, body=None, **kwargs):
    return SimpleNamespace(
        status=status,
        body=body,
        header=kwargs.pop("header", []),
        **kwargs,
    )


def _metadata_body(
    *,
    content_length=12,
    content_type="text/plain",
    last_modified="2026-06-13T10:00:00Z",
    etag="etag-1",
    storage_class="STANDARD",
):
    return SimpleNamespace(
        contentLength=content_length,
        contentType=content_type,
        lastModified=last_modified,
        etag=etag,
        storageClass=storage_class,
    )


def test_fetch_obs_objects_parses_list_response():
    item = SimpleNamespace(
        key="logs/app.log",
        size=123,
        lastModified="2026-06-13T10:00:00Z",
        etag="etag-1",
        storageClass="STANDARD",
    )
    client = MagicMock()
    client.listObjects.return_value = _response(
        body=SimpleNamespace(contents=[item]),
    )

    with patch("app.tools.obs_tools.ObsClient", return_value=client) as mock_client:
        result = fetch_obs_objects(
            bucket="my-bucket",
            prefix="logs/",
            limit=20,
            sts_credentials=_sts(),
        )

    assert result == [
        {
            "bucket": "my-bucket",
            "key": "logs/app.log",
            "size": 123,
            "last_modified": "2026-06-13T10:00:00Z",
            "etag": "etag-1",
            "storage_class": "STANDARD",
        }
    ]
    mock_client.assert_called_once_with(
        access_key_id="ak",
        secret_access_key="sk",
        security_token="token",
        server=DEFAULT_OBS_ENDPOINT,
    )
    client.listObjects.assert_called_once_with(
        "my-bucket",
        prefix="logs/",
        max_keys=20,
    )


def test_fetch_obs_objects_clamps_limit():
    client = MagicMock()
    client.listObjects.return_value = _response(body=SimpleNamespace(contents=[]))

    with patch("app.tools.obs_tools.ObsClient", return_value=client):
        fetch_obs_objects(
            bucket="my-bucket",
            prefix="",
            limit=1000,
            sts_credentials=_sts(),
        )

    client.listObjects.assert_called_once_with(
        "my-bucket",
        prefix=None,
        max_keys=100,
    )


def test_fetch_obs_object_metadata_parses_head_response():
    client = MagicMock()
    client.getObjectMetadata.return_value = _response(
        body=_metadata_body(content_length=99, content_type="application/json"),
        header=[("x-obs-meta-owner", "platform")],
    )

    with patch("app.tools.obs_tools.ObsClient", return_value=client):
        result = fetch_obs_object_metadata(
            bucket="my-bucket",
            key="config.json",
            sts_credentials=_sts(),
        )

    assert result == {
        "bucket": "my-bucket",
        "key": "config.json",
        "size": 99,
        "content_type": "application/json",
        "last_modified": "2026-06-13T10:00:00Z",
        "etag": "etag-1",
        "storage_class": "STANDARD",
        "metadata": {"owner": "platform"},
    }


def test_fetch_obs_text_object_reads_text_range():
    client = MagicMock()
    client.getObjectMetadata.return_value = _response(
        body=_metadata_body(content_length=20, content_type="application/json"),
    )
    client.getObject.return_value = _response(body=b'{"ok": true}')

    with patch("app.tools.obs_tools.ObsClient", return_value=client):
        result = fetch_obs_text_object(
            bucket="my-bucket",
            key="config.json",
            max_bytes=10,
            sts_credentials=_sts(),
        )

    assert result["content"] == '{"ok": tru'
    assert result["truncated"] is True
    assert result["encoding"] == "utf-8"
    assert result["bytes_read"] == 10
    _, kwargs = client.getObject.call_args
    assert kwargs["loadStreamInMemory"] is True
    assert kwargs["headers"].range == "bytes=0-9"


def test_fetch_obs_text_object_allows_text_extension_without_content_type():
    client = MagicMock()
    client.getObjectMetadata.return_value = _response(
        body=_metadata_body(content_length=5, content_type=None),
    )
    client.getObject.return_value = _response(body=b"hello")

    with patch("app.tools.obs_tools.ObsClient", return_value=client):
        result = fetch_obs_text_object(
            bucket="my-bucket",
            key="logs/app.log",
            sts_credentials=_sts(),
        )

    assert result["content"] == "hello"


def test_fetch_obs_text_object_rejects_binary_object():
    client = MagicMock()
    client.getObjectMetadata.return_value = _response(
        body=_metadata_body(content_type="application/octet-stream"),
    )

    with (
        patch("app.tools.obs_tools.ObsClient", return_value=client),
        pytest.raises(OBSToolError, match="does not look like a text file"),
    ):
        fetch_obs_text_object(
            bucket="my-bucket",
            key="archive.zip",
            sts_credentials=_sts(),
        )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "authorization failed"),
        (403, "denied"),
        (404, "was not found"),
        (500, "status 500"),
    ],
)
def test_fetch_obs_objects_converts_obs_errors(status_code, expected):
    client = MagicMock()
    client.listObjects.return_value = _response(
        status=status_code,
        body=None,
        errorCode="Bad",
        errorMessage="bad things",
    )

    with (
        patch("app.tools.obs_tools.ObsClient", return_value=client),
        pytest.raises(OBSToolError, match=expected),
    ):
        fetch_obs_objects(bucket="my-bucket", sts_credentials=_sts())


@pytest.mark.asyncio
async def test_list_obs_objects_original_function_requires_sts_credentials():
    with pytest.raises(OBSToolError, match="Missing Huawei Cloud STS credentials"):
        await _list_obs_objects_impl(bucket="my-bucket", sts_credentials=None)


def test_sts_credentials_are_not_part_of_tool_schema():
    list_schema = list_obs_objects.tool_call_schema.model_json_schema()
    metadata_schema = get_obs_object_metadata.tool_call_schema.model_json_schema()
    read_schema = read_obs_text_object.tool_call_schema.model_json_schema()

    assert "sts_credentials" not in list_schema["properties"]
    assert "sts_credentials" not in metadata_schema["properties"]
    assert "sts_credentials" not in read_schema["properties"]
