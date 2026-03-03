"""Memory compression and summarization.

Reduces memory size while preserving key information:
- Text summarization
- Key point extraction
- Importance-based filtering
"""

from datetime import datetime, timedelta

from core.memory.types import MemoryCompressionResult, MemoryEntry


class MemoryCompressor:
    """Compress memories to reduce storage and improve retrieval."""

    def __init__(self, max_summary_length: int = 500):
        """Initialize compressor.

        Args:
            max_summary_length: Maximum length of compressed summary
        """
        self.max_summary_length = max_summary_length

    async def compress(self, entry: MemoryEntry) -> MemoryCompressionResult:
        """Compress a memory entry.

        Args:
            entry: Memory entry to compress

        Returns:
            Compression result
        """
        original_length = len(entry.content)

        # Generate summary
        summary = await self._summarize(entry.content)

        # Extract key points
        key_points = await self._extract_key_points(entry.content)

        # Build compressed summary
        compressed = self._build_compressed_summary(summary, key_points)

        compression_ratio = len(compressed) / original_length if original_length > 0 else 1.0

        return MemoryCompressionResult(
            original_entry=entry,
            compressed_summary=compressed,
            compression_ratio=compression_ratio,
            preserved_keys=key_points,
        )

    async def _summarize(self, content: str) -> str:
        """Generate summary of content.

        For production, use LLM-based summarization.
        """
        # Simple extraction-based summarization
        lines = content.split("\n")

        # Extract headers and important lines
        important_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Headers (markdown style)
            if (
                line.startswith("#")
                or ":" in line
                and len(line) < 100
                or line.startswith(("-", "*", "•"))
            ):
                important_lines.append(line)

        summary = "\n".join(important_lines[:10])  # Top 10 important lines

        if len(summary) > self.max_summary_length:
            summary = summary[: self.max_summary_length] + "..."

        return summary

    async def _extract_key_points(self, content: str) -> list[str]:
        """Extract key points from content."""
        key_points = []

        lines = content.split("\n")
        for line in lines:
            line = line.strip()

            # Decision statements
            if any(kw in line.lower() for kw in ["decided", "decision", "chose", "selected"]):
                key_points.append(line)

            # Important findings
            if any(kw in line.lower() for kw in ["important", "critical", "key", "essential"]):
                key_points.append(line)

            # Constraints
            if any(kw in line.lower() for kw in ["constraint", "limitation", "must", "should"]):
                key_points.append(line)

        return key_points[:5]  # Top 5 key points

    def _build_compressed_summary(
        self,
        summary: str,
        key_points: list[str],
    ) -> str:
        """Build final compressed summary."""
        parts = []

        if summary:
            parts.append("## Summary\n" + summary)

        if key_points:
            parts.append("\n## Key Points")
            for i, point in enumerate(key_points, 1):
                parts.append(f"{i}. {point}")

        result = "\n".join(parts)

        if len(result) > self.max_summary_length:
            result = result[: self.max_summary_length] + "..."

        return result

    async def should_compress(self, entry: MemoryEntry) -> bool:
        """Determine if entry should be compressed.

        Compression triggers:
        - Content is very long
        - Entry is old
        - Entry has been accessed many times
        - Entry has low importance

        Args:
            entry: Memory entry

        Returns:
            True if should compress
        """
        # Long content
        if len(entry.content) > 2000:
            return True

        # Old entry (older than 24 hours)
        age = datetime.utcnow() - entry.created_at
        if age > timedelta(hours=24):
            return True

        # Frequently accessed
        if entry.access_count > 10:
            return True

        # Low importance
        return entry.importance < 0.3

    async def compress_batch(
        self,
        entries: list[MemoryEntry],
    ) -> list[MemoryCompressionResult]:
        """Compress multiple entries.

        Args:
            entries: Entries to compress

        Returns:
            Compression results
        """
        results = []

        for entry in entries:
            if await self.should_compress(entry):
                result = await self.compress(entry)
                results.append(result)

                # Update entry with compressed summary
                entry.summary = result.compressed_summary

        return results


class MemoryPruner:
    """Prune old/low-importance memories to manage storage."""

    def __init__(
        self,
        max_age_days: int = 30,
        min_importance: float = 0.2,
    ):
        """Initialize pruner.

        Args:
            max_age_days: Maximum age before pruning
            min_importance: Minimum importance to keep
        """
        self.max_age_days = max_age_days
        self.min_importance = min_importance

    def should_prune(self, entry: MemoryEntry) -> bool:
        """Determine if entry should be pruned.

        Args:
            entry: Memory entry

        Returns:
            True if should prune
        """
        # Never prune high-importance entries
        if entry.importance > 0.8:
            return False

        # Never prune entries with positive feedback
        if entry.feedback_positive is True:
            return False

        # Check age
        age = datetime.utcnow() - entry.created_at
        if age > timedelta(days=self.max_age_days) and entry.importance < self.min_importance:
            return True

        # Prune entries with negative feedback
        return entry.feedback_positive is False

    async def prune_batch(
        self,
        entries: list[MemoryEntry],
    ) -> list[MemoryEntry]:
        """Filter entries to prune.

        Args:
            entries: All entries

        Returns:
            Entries to prune
        """
        return [e for e in entries if self.should_prune(e)]


class MemoryConsolidator:
    """Consolidate similar memories to reduce redundancy."""

    def __init__(self, similarity_threshold: float = 0.85):
        """Initialize consolidator.

        Args:
            similarity_threshold: Similarity threshold for merging
        """
        self.similarity_threshold = similarity_threshold

    async def find_similar_pairs(
        self,
        entries: list[MemoryEntry],
    ) -> list[tuple[MemoryEntry, MemoryEntry, float]]:
        """Find pairs of similar memories.

        Args:
            entries: Memory entries

        Returns:
            List of (entry1, entry2, similarity) tuples
        """
        pairs = []

        for i, e1 in enumerate(entries):
            for e2 in entries[i + 1 :]:
                similarity = self._calculate_similarity(e1, e2)
                if similarity >= self.similarity_threshold:
                    pairs.append((e1, e2, similarity))

        return pairs

    def _calculate_similarity(self, e1: MemoryEntry, e2: MemoryEntry) -> float:
        """Calculate similarity between two entries.

        Uses simple Jaccard similarity on tags and content keywords.
        """
        # Tag overlap
        tag_overlap = len(set(e1.tags) & set(e2.tags))
        tag_union = len(set(e1.tags) | set(e2.tags))
        tag_sim = tag_overlap / tag_union if tag_union > 0 else 0

        # Agent match
        agent_sim = 1.0 if e1.agent_name == e2.agent_name else 0.0

        # Type match
        type_sim = 1.0 if e1.type == e2.type else 0.0

        # Combined similarity
        return (tag_sim * 0.5) + (agent_sim * 0.25) + (type_sim * 0.25)

    async def merge_entries(
        self,
        e1: MemoryEntry,
        e2: MemoryEntry,
    ) -> MemoryEntry:
        """Merge two similar entries.

        Args:
            e1: First entry
            e2: Second entry

        Returns:
            Merged entry
        """
        # Use newer entry as base
        if e2.created_at > e1.created_at:
            e1, e2 = e2, e1

        # Merge content
        merged_content = e1.content + "\n\n---\n\n" + e2.content

        # Merge tags
        merged_tags = list(set(e1.tags) | set(e2.tags))

        # Merge metadata
        merged_metadata = {**e1.metadata, **e2.metadata}

        # Update importance (max of both)
        merged_importance = max(e1.importance, e2.importance)

        # Create merged entry
        merged = MemoryEntry(
            id=e1.id,  # Keep first entry's ID
            type=e1.type,
            scope=e1.scope,
            session_id=e1.session_id,
            project_id=e1.project_id or e2.project_id,
            agent_name=e1.agent_name,
            content=merged_content,
            summary=f"Merged: {e1.summary or ''} | {e2.summary or ''}",
            tags=merged_tags,
            importance=merged_importance,
            metadata=merged_metadata,
            created_at=e1.created_at,
            updated_at=datetime.utcnow(),
            access_count=e1.access_count + e2.access_count,
        )

        return merged
