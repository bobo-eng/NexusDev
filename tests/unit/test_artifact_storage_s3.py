"""Tests for S3 artifact storage."""

from io import BytesIO
from uuid import uuid4

import pytest
from core.domain.artifact import Artifact, ArtifactType
from core.storage.artifact_storage import S3ArtifactStorage


class FakeS3Client:
    """Simple in-memory fake S3 client for unit tests."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}

    def put_object(self, **kwargs: object) -> dict:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = kwargs["Body"]
        if not isinstance(body, bytes):
            raise TypeError("Body must be bytes")
        content_type_raw = kwargs.get("ContentType")
        content_type = str(content_type_raw) if content_type_raw is not None else None
        self.objects[(bucket, key)] = (body, content_type)
        return {}

    def get_object(self, **kwargs: object) -> dict:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body, content_type = self.objects[(bucket, key)]
        return {
            "Body": BytesIO(body),
            "ContentType": content_type,
        }

    def delete_object(self, **kwargs: object) -> dict:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        self.objects.pop((bucket, key), None)
        return {}


def _make_artifact(
    *,
    content: str = "hello world",
    content_type: str = "text/plain",
    name: str = "design.md",
) -> Artifact:
    return Artifact(
        session_id=uuid4(),
        name=name,
        artifact_type=ArtifactType.SYSTEM_DESIGN,
        content=content,
        content_type=content_type,
    )


def _parse_s3_path(path: str) -> tuple[str, str]:
    raw = path.removeprefix("s3://")
    bucket, _, key = raw.partition("/")
    return bucket, key


@pytest.mark.asyncio
async def test_s3_store_and_load_text() -> None:
    """Should store text to S3 and load it back as string."""
    client = FakeS3Client()
    storage = S3ArtifactStorage(
        bucket="test-bucket",
        prefix="artifacts",
        s3_client=client,
    )
    artifact = _make_artifact(content="system architecture")

    stored = await storage.store(artifact)

    assert stored.file_path is not None
    assert stored.file_path.startswith("s3://test-bucket/artifacts/")
    assert stored.content == ""
    assert stored.checksum is not None

    loaded = await storage.load(stored)
    assert loaded == "system architecture"


@pytest.mark.asyncio
async def test_s3_store_and_load_binary() -> None:
    """Should keep binary payload as bytes on load."""
    client = FakeS3Client()
    storage = S3ArtifactStorage(
        bucket="test-bucket",
        prefix="artifacts",
        s3_client=client,
    )
    artifact = _make_artifact(content="", content_type="application/octet-stream", name="bundle.bin")
    payload = b"\x00\x01\x02\x03"

    stored = await storage.store(artifact, content=payload)
    loaded = await storage.load(stored)

    assert loaded == payload


@pytest.mark.asyncio
async def test_s3_verify_detects_tamper() -> None:
    """Verify should fail if object content changes after store."""
    client = FakeS3Client()
    storage = S3ArtifactStorage(
        bucket="test-bucket",
        prefix="artifacts",
        s3_client=client,
    )
    artifact = _make_artifact(content="original content")
    stored = await storage.store(artifact)

    assert await storage.verify(stored) is True

    bucket, key = _parse_s3_path(stored.file_path or "")
    client.objects[(bucket, key)] = (b"tampered", "text/plain")

    assert await storage.verify(stored) is False


@pytest.mark.asyncio
async def test_s3_delete_and_missing_load() -> None:
    """Deleted object should not be loadable anymore."""
    client = FakeS3Client()
    storage = S3ArtifactStorage(
        bucket="test-bucket",
        prefix="artifacts",
        s3_client=client,
    )
    artifact = _make_artifact(content="temporary")
    stored = await storage.store(artifact)

    deleted = await storage.delete(stored)
    assert deleted is True

    with pytest.raises(FileNotFoundError):
        await storage.load(stored)
