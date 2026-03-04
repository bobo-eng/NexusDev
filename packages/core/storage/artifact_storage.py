"""Artifact storage with分层设计.

分层存储:
- DB: 只存元数据 (id, name, type, file_path, size, checksum)
- FileSystem/S3: 存实际内容

Benefits:
- 避免大文本撑爆 DB 事务
- 更快的查询性能
- 支持大文件/二进制
"""

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import aiofiles

from core.domain.artifact import Artifact

logger = logging.getLogger(__name__)


class ArtifactStorage:
    """分层 artifact 存储.

    元数据存 DB，内容存文件系统。
    """

    def __init__(self, base_path: str = "./artifacts"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_artifact_path(self, session_id: UUID, artifact_id: UUID, name: str) -> Path:
        """Get storage path for artifact."""
        # Organize by session for easier cleanup
        session_dir = self.base_path / str(session_id)
        session_dir.mkdir(exist_ok=True)

        # Use artifact_id as filename to avoid conflicts
        # Keep original extension
        suffix = Path(name).suffix
        return session_dir / f"{artifact_id}{suffix}"

    def _compute_checksum(self, content: str | bytes) -> str:
        """Compute SHA-256 checksum."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    async def store(
        self,
        artifact: Artifact,
        content: str | bytes | None = None,
    ) -> Artifact:
        """Store artifact content to filesystem.

        Args:
            artifact: Artifact entity
            content: Content to store (uses artifact.content if None)

        Returns:
            Updated artifact with file_path and checksum
        """
        if content is None:
            content = artifact.content

        if not content:
            logger.warning(f"Artifact {artifact.id} has no content to store")
            return artifact

        # Determine file path
        file_path = self._get_artifact_path(
            artifact.session_id,
            artifact.id,
            artifact.name,
        )

        # Write content
        if isinstance(content, str):
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
        else:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)

        # Compute checksum
        checksum = self._compute_checksum(content)
        file_size = len(content.encode("utf-8")) if isinstance(content, str) else len(content)

        # Update artifact
        artifact.file_path = str(file_path)
        artifact.file_size = file_size
        artifact.checksum = checksum

        # Clear inline content (stored in filesystem now)
        # Keep a summary for quick access
        artifact.content = ""

        logger.info(
            f"Stored artifact {artifact.id} to {file_path} "
            f"(size={file_size}, checksum={checksum[:16]}...)"
        )

        return artifact

    async def load(self, artifact: Artifact) -> str | bytes:
        """Load artifact content from filesystem.

        Args:
            artifact: Artifact entity

        Returns:
            Artifact content

        Raises:
            FileNotFoundError: If file not found
        """
        if not artifact.file_path:
            # Fallback to inline content
            return artifact.content

        file_path = Path(artifact.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Artifact file not found: {file_path}")

        # Determine if binary
        is_binary = (
            artifact.content_type.startswith("application/")
            or artifact.content_type.startswith("image/")
            or artifact.content_type.startswith("video/")
        )

        if is_binary:
            async with aiofiles.open(file_path, "rb") as f:
                return await f.read()
        else:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                return await f.read()

    async def delete(self, artifact: Artifact) -> bool:
        """Delete artifact from filesystem.

        Args:
            artifact: Artifact entity

        Returns:
            True if deleted
        """
        if not artifact.file_path:
            return False

        file_path = Path(artifact.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted artifact file: {file_path}")
            return True

        return False

    async def verify(self, artifact: Artifact) -> bool:
        """Verify artifact integrity.

        Args:
            artifact: Artifact entity

        Returns:
            True if checksum matches
        """
        if not artifact.file_path or not artifact.checksum:
            return False

        try:
            content = await self.load(artifact)
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content
            computed = self._compute_checksum(content_bytes)
            return computed == artifact.checksum
        except Exception as e:
            logger.error(f"Failed to verify artifact {artifact.id}: {e}")
            return False

    async def get_summary(
        self,
        artifact: Artifact,
        max_length: int = 500,
    ) -> str:
        """Get content summary.

        Args:
            artifact: Artifact entity
            max_length: Maximum summary length

        Returns:
            Content summary
        """
        try:
            content = await self.load(artifact)
            content_str = content if isinstance(content, str) else "<binary content>"

            if len(content_str) <= max_length:
                return content_str

            return content_str[:max_length] + "..."
        except Exception as e:
            return f"<failed to load: {e}>"


class S3ArtifactStorage(ArtifactStorage):
    """S3-based artifact storage.

    For production use with S3-compatible storage.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "artifacts",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        s3_client: Any | None = None,
    ):
        if not bucket.strip():
            raise ValueError("bucket must not be empty")

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self.region_name = region_name

        if s3_client is not None:
            self._client = s3_client
            return

        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for S3ArtifactStorage; install boto3 or inject s3_client."
            ) from exc

        client_kwargs: dict[str, Any] = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region_name:
            client_kwargs["region_name"] = region_name

        self._client = boto3.client("s3", **client_kwargs)

    def _get_artifact_key(
        self,
        session_id: UUID,
        artifact_id: UUID,
        name: str,
    ) -> str:
        """Build S3 object key for an artifact."""
        suffix = Path(name).suffix
        filename = f"{artifact_id}{suffix}"
        if self.prefix:
            return f"{self.prefix}/{session_id}/{filename}"
        return f"{session_id}/{filename}"

    def _resolve_bucket_and_key(
        self,
        artifact: Artifact,
    ) -> tuple[str, str]:
        """Resolve bucket/key from artifact file path or artifact identity."""
        if artifact.file_path:
            if artifact.file_path.startswith("s3://"):
                raw = artifact.file_path[len("s3://") :]
                bucket, separator, key = raw.partition("/")
                if not separator or not key:
                    raise ValueError(f"Invalid S3 file path: {artifact.file_path}")
                return bucket, key

            return self.bucket, artifact.file_path.lstrip("/")

        return self.bucket, self._get_artifact_key(artifact.session_id, artifact.id, artifact.name)

    @staticmethod
    def _is_not_found_error(error: Exception) -> bool:
        """Check whether an S3 exception represents not-found."""
        if isinstance(error, (FileNotFoundError, KeyError)):
            return True

        response = getattr(error, "response", None)
        if isinstance(response, dict):
            code = str(response.get("Error", {}).get("Code", ""))
            return code in {"404", "NoSuchKey", "NotFound"}

        return False

    async def store(
        self,
        artifact: Artifact,
        content: str | bytes | None = None,
    ) -> Artifact:
        """Store artifact content to S3."""
        if content is None:
            content = artifact.content

        if not content:
            logger.warning(f"Artifact {artifact.id} has no content to store")
            return artifact

        key = self._get_artifact_key(artifact.session_id, artifact.id, artifact.name)
        body = content.encode("utf-8") if isinstance(content, str) else content

        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=artifact.content_type,
        )

        checksum = self._compute_checksum(body)
        file_size = len(body)

        artifact.file_path = f"s3://{self.bucket}/{key}"
        artifact.file_size = file_size
        artifact.checksum = checksum
        artifact.content = ""

        logger.info(
            f"Stored artifact {artifact.id} to s3://{self.bucket}/{key} "
            f"(size={file_size}, checksum={checksum[:16]}...)"
        )

        return artifact

    async def load(self, artifact: Artifact) -> str | bytes:
        """Load artifact content from S3."""
        if not artifact.file_path:
            return artifact.content

        bucket, key = self._resolve_bucket_and_key(artifact)

        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=bucket,
                Key=key,
            )
        except Exception as exc:
            if self._is_not_found_error(exc):
                raise FileNotFoundError(f"Artifact object not found: s3://{bucket}/{key}") from exc
            raise

        body_stream = response.get("Body")
        if hasattr(body_stream, "read"):
            body = await asyncio.to_thread(body_stream.read)
        elif isinstance(body_stream, bytes):
            body = body_stream
        else:
            body = b""

        content_type = artifact.content_type or response.get("ContentType", "")
        is_binary = (
            content_type.startswith("application/")
            or content_type.startswith("image/")
            or content_type.startswith("video/")
        )
        if is_binary:
            return body

        return body.decode("utf-8")

    async def delete(self, artifact: Artifact) -> bool:
        """Delete artifact object from S3."""
        if not artifact.file_path:
            return False

        bucket, key = self._resolve_bucket_and_key(artifact)
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=bucket,
            Key=key,
        )

        logger.info(f"Deleted artifact object: s3://{bucket}/{key}")
        return True


async def store_artifact_with_content(
    artifact: Artifact,
    storage: ArtifactStorage | None = None,
    max_inline_size: int = 1024,  # 1KB threshold for inline storage
) -> Artifact:
    """Store artifact with automatic storage strategy.

    Small content: inline in DB
    Large content: filesystem storage

    Args:
        artifact: Artifact entity
        storage: ArtifactStorage instance
        max_inline_size: Maximum size for inline storage

    Returns:
        Updated artifact
    """
    if storage is None:
        storage = ArtifactStorage()

    content = artifact.content
    if not content:
        return artifact

    content_size = len(content.encode("utf-8"))

    if content_size <= max_inline_size:
        # Small content: keep inline
        artifact.checksum = storage._compute_checksum(content)
        artifact.file_size = content_size
        logger.debug(f"Stored artifact {artifact.id} inline (size={content_size})")
    else:
        # Large content: filesystem storage
        artifact = await storage.store(artifact)

    return artifact
