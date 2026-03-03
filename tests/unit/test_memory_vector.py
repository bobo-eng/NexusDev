"""Tests for vector store backends."""

from uuid import uuid4

import pytest

from core.memory.retrieval.vector import QdrantVectorStore


@pytest.mark.asyncio
async def test_qdrant_store_local_mode_and_filter_search() -> None:
    """Qdrant local mode should work without sentence-transformers."""
    pytest.importorskip("qdrant_client")

    collection = f"nexusdev_test_{uuid4().hex}"
    store = QdrantVectorStore(url=":memory:", collection=collection)

    assert store._client is not None

    query_embedding = await store.embed("todo create endpoint")
    other_embedding = await store.embed("vector database integration")

    assert len(query_embedding) == store.embedding_dim
    assert len(other_embedding) == store.embedding_dim

    match_id = uuid4()
    mismatch_id = uuid4()

    await store.index(match_id, query_embedding, {"type": "semantic", "agent": "tester"})
    await store.index(mismatch_id, other_embedding, {"type": "other", "agent": "tester"})

    results = await store.search(query_embedding, top_k=5, filters={"type": "semantic"})
    result_ids = [entry_id for entry_id, _score in results]

    assert match_id in result_ids
    assert mismatch_id not in result_ids
