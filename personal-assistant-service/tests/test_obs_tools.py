"""Unit tests for app.tools.obs_tools — mock ObsClient responses."""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_obs_config(monkeypatch):
    """Ensure OBS config env vars are set to avoid config.yaml loading issues."""
    monkeypatch.setenv("OBS_ENDPOINT", "https://obs.test.example.com")
    monkeypatch.setenv("OBS_STS_PROVIDER_NAME", "test-sts-provider")


@pytest.fixture
def mock_obs_client():
    """Mock ObsClient to simulate OBS API responses.

    Patches obs.ObsClient (the imported symbol) rather than
    app.tools.obs_tools.ObsClient, because ObsClient is lazily imported
    inside _make_obs_client() via ``from obs import ObsClient`` and
    never becomes a module-level attribute of obs_tools.
    """
    with patch("obs.ObsClient") as mock_class:
        yield mock_class


def _make_list_objects_response(keys_and_sizes, is_truncated=False):
    """Create a mock listObjects response body."""
    body = MagicMock()
    contents = []
    for key, size in keys_and_sizes:
        obj = MagicMock()
        obj.key = key
        obj.size = size
        obj.lastModified = "2026-06-09T10:00:00Z"
        contents.append(obj)
    body.contents = contents
    body.isTruncated = is_truncated
    return body


def _make_get_object_response(data_bytes: bytes):
    """Create a mock getObject response."""
    resp = MagicMock()
    resp.body.buffer = data_bytes
    return resp


def _make_get_metadata_response(content_type, content_length, last_modified, etag):
    """Create a mock getObjectMetadata response."""
    resp = MagicMock()
    resp.body.contentType = content_type
    resp.body.contentLength = content_length
    resp.body.lastModified = last_modified
    resp.body.etag = etag
    return resp


# ── list_obs_objects tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_obs_objects_returns_list(mock_obs_config, mock_obs_client):
    """Mock listObjects returning objects — verify formatted output."""
    from app.tools.obs_tools import list_obs_objects

    mock_client = mock_obs_client.return_value
    mock_client.listObjects.return_value.body = _make_list_objects_response(
        [("logs/app.log", 2048), ("logs/error.log", 512)]
    )

    result = await list_obs_objects(
        bucket="my-bucket",
        prefix="logs/",
        limit=100,
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["bucket"] == "my-bucket"
    assert result["prefix"] == "logs/"
    assert len(result["objects"]) == 2
    assert result["objects"][0]["key"] == "logs/app.log"
    assert result["objects"][0]["size"] == 2048
    assert "last_modified" in result["objects"][0]


@pytest.mark.asyncio
async def test_list_obs_objects_with_prefix_filter(mock_obs_config, mock_obs_client):
    """Verify prefix parameter is passed to listObjects."""
    from app.tools.obs_tools import list_obs_objects

    mock_client = mock_obs_client.return_value
    mock_client.listObjects.return_value.body = _make_list_objects_response([])

    await list_obs_objects(
        bucket="my-bucket",
        prefix="data/2026/",
        limit=50,
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    # Verify prefix was passed to SDK
    mock_client.listObjects.assert_called_once()
    call_kwargs = mock_client.listObjects.call_args[1]
    assert call_kwargs["prefix"] == "data/2026/"
    assert call_kwargs["max_keys"] == 50


@pytest.mark.asyncio
async def test_list_obs_objects_empty_bucket(mock_obs_config, mock_obs_client):
    """Mock listObjects returning empty contents — verify empty list."""
    from app.tools.obs_tools import list_obs_objects

    mock_client = mock_obs_client.return_value
    mock_client.listObjects.return_value.body = _make_list_objects_response([])

    result = await list_obs_objects(
        bucket="empty-bucket",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["objects"] == []


# ── get_obs_object tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_obs_object_text_file(mock_obs_config, mock_obs_client):
    """Mock getObject returning a .txt file — verify text content."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    mock_client.getObject.return_value = _make_get_object_response(
        b"Hello, World!\nLine 2\n"
    )

    result = await get_obs_object(
        bucket="my-bucket",
        key="notes.txt",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["content_type"] == "text"
    assert result["content"] == "Hello, World!\nLine 2\n"
    assert result["size"] == 21  # "Hello, World!\nLine 2\n" = 21 bytes
    assert result["truncated"] is False
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "notes.txt"


@pytest.mark.asyncio
async def test_get_obs_object_json_file(mock_obs_config, mock_obs_client):
    """Mock getObject returning a .json file — verify parsed and formatted."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    data = {"name": "test", "values": [1, 2, 3]}
    mock_client.getObject.return_value = _make_get_object_response(
        json.dumps(data).encode("utf-8")
    )

    result = await get_obs_object(
        bucket="my-bucket",
        key="config.json",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["content_type"] == "json"
    parsed = json.loads(result["content"])
    assert parsed["name"] == "test"
    assert parsed["values"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_obs_object_binary_file(mock_obs_config, mock_obs_client):
    """Mock getObject returning a .pdf (binary) — verify content=null."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    mock_client.getObject.return_value = _make_get_object_response(
        b"\x00\x01\x02\x03binary\xff"
    )

    result = await get_obs_object(
        bucket="my-bucket",
        key="report.pdf",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["content_type"] == "binary"
    assert result["content"] is None
    assert result["note"] == "二进制文件，无法以文本形式展示"


@pytest.mark.asyncio
async def test_get_obs_object_markdown_file(mock_obs_config, mock_obs_client):
    """Mock getObject returning a .md file — verify text content."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    mock_client.getObject.return_value = _make_get_object_response(
        b"# Title\n\nContent here.\n"
    )

    result = await get_obs_object(
        bucket="my-bucket",
        key="README.md",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["content_type"] == "text"
    assert result["content"] == "# Title\n\nContent here.\n"


@pytest.mark.asyncio
async def test_get_obs_object_bucket_not_found(mock_obs_config, mock_obs_client):
    """Mock NoSuchBucket exception — verify error dict."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value

    # Simulate OBS SDK exception with get_error_code/get_error_message
    class NoSuchBucketError(Exception):
        def get_error_code(self):
            return "NoSuchBucket"

        def get_error_message(self):
            return "The specified bucket does not exist"

    mock_client.getObject.side_effect = NoSuchBucketError()

    result = await get_obs_object(
        bucket="no-such-bucket",
        key="test.txt",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert "error" in result
    assert "NoSuchBucket" in result["error"]


@pytest.mark.asyncio
async def test_get_obs_object_key_not_found(mock_obs_config, mock_obs_client):
    """Mock NoSuchKey exception — verify error dict."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value

    class NoSuchKeyError(Exception):
        def get_error_code(self):
            return "NoSuchKey"

        def get_error_message(self):
            return "The specified key does not exist"

    mock_client.getObject.side_effect = NoSuchKeyError()

    result = await get_obs_object(
        bucket="my-bucket",
        key="nonexistent.txt",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert "error" in result
    assert "NoSuchKey" in result["error"]


# ── get_obs_object_metadata tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_obs_object_metadata_returns_info(mock_obs_config, mock_obs_client):
    """Mock getObjectMetadata — verify metadata fields."""
    from app.tools.obs_tools import get_obs_object_metadata

    mock_client = mock_obs_client.return_value
    mock_client.getObjectMetadata.return_value = _make_get_metadata_response(
        content_type="application/json",
        content_length=4096,
        last_modified="2026-06-09T10:00:00Z",
        etag="abc123def456",
    )

    result = await get_obs_object_metadata(
        bucket="my-bucket",
        key="config.json",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["bucket"] == "my-bucket"
    assert result["key"] == "config.json"
    assert result["content_type"] == "application/json"
    assert result["size"] == 4096
    assert result["last_modified"] == "2026-06-09T10:00:00Z"
    assert result["etag"] == "abc123def456"


# ── Additional error / edge case tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_obs_objects_error(mock_obs_config, mock_obs_client):
    """Mock generic SDK exception — verify error dict with bucket/prefix."""
    from app.tools.obs_tools import list_obs_objects

    mock_client = mock_obs_client.return_value
    mock_client.listObjects.side_effect = RuntimeError("Connection refused")

    result = await list_obs_objects(
        bucket="my-bucket",
        prefix="logs/",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert "error" in result
    assert result["bucket"] == "my-bucket"
    assert result["prefix"] == "logs/"


@pytest.mark.asyncio
async def test_get_obs_object_metadata_error(mock_obs_config, mock_obs_client):
    """Mock SDK exception on getObjectMetadata — verify error dict."""
    from app.tools.obs_tools import get_obs_object_metadata

    mock_client = mock_obs_client.return_value

    class AccessDeniedError(Exception):
        def get_error_code(self):
            return "AccessDenied"

        def get_error_message(self):
            return "Access denied"

    mock_client.getObjectMetadata.side_effect = AccessDeniedError()

    result = await get_obs_object_metadata(
        bucket="my-bucket",
        key="secret.txt",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert "error" in result
    assert "AccessDenied" in result["error"]
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "secret.txt"


@pytest.mark.asyncio
async def test_get_obs_object_corrupt_json(mock_obs_config, mock_obs_client):
    """Mock getObject returning corrupt JSON — verify fallback to text."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    mock_client.getObject.return_value = _make_get_object_response(
        b"{invalid json content!!!"
    )

    result = await get_obs_object(
        bucket="my-bucket",
        key="bad.json",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    # Corrupt JSON should be treated as text (fallback)
    assert result["content_type"] == "text"
    assert result["content"] == "{invalid json content!!!"


@pytest.mark.asyncio
async def test_get_obs_object_large_file_truncated(mock_obs_config, mock_obs_client):
    """Mock getObject returning > 1MB — verify truncated=True."""
    from app.tools.obs_tools import get_obs_object

    mock_client = mock_obs_client.return_value
    # Create data just over 1MB to trigger truncation
    large_data = b"x" * (1024 * 1024 + 100)
    mock_client.getObject.return_value = _make_get_object_response(large_data)

    result = await get_obs_object(
        bucket="my-bucket",
        key="large.txt",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert result["truncated"] is True
    assert result["size"] == 1024 * 1024 + 100
    assert len(result["content"]) < result["size"]  # content is truncated


@pytest.mark.asyncio
async def test_list_obs_objects_sdk_error_with_code(mock_obs_config, mock_obs_client):
    """Mock OBS SDK exception with get_error_code/get_error_message — verify formatted error."""
    from app.tools.obs_tools import list_obs_objects

    mock_client = mock_obs_client.return_value

    class InvalidBucketError(Exception):
        def get_error_code(self):
            return "InvalidBucketName"

        def get_error_message(self):
            return "The specified bucket name is invalid"

    mock_client.listObjects.side_effect = InvalidBucketError()

    result = await list_obs_objects(
        bucket="bad_bucket",
        sts_credentials=MagicMock(
            access_key_id="ak", secret_access_key="sk", security_token="st"
        ),
    )

    assert "InvalidBucketName" in result["error"]
    assert "The specified bucket name is invalid" in result["error"]
