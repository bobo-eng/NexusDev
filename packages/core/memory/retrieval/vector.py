"""Vector store for semantic similarity search.

Supports:
- Text embedding generation
- Vector indexing
- Similarity search
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

import numpy as np


class VectorStore(ABC):
    """Abstract vector store interface."""
    
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        pass
    
    @abstractmethod
    async def index(self, id: UUID, embedding: list[float], metadata: dict) -> None:
        """Index an embedding."""
        pass
    
    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[tuple[UUID, float]]:
        """Search for similar embeddings."""
        pass


class SimpleVectorStore(VectorStore):
    """Simple in-memory vector store using cosine similarity.
    
    For production, replace with Qdrant, Pinecone, or similar.
    """
    
    def __init__(self, embedding_dim: int = 384):
        """Initialize vector store.
        
        Args:
            embedding_dim: Dimension of embeddings
        """
        self.embedding_dim = embedding_dim
        self._vectors: dict[UUID, np.ndarray] = {}
        self._metadata: dict[UUID, dict] = {}
        
        # Simple embedding model (for demo - use real model in production)
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
        except ImportError:
            self._model = None
    
    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text.
        
        Uses sentence-transformers if available, otherwise simple hash-based.
        """
        if self._model:
            embedding = self._model.encode(text)
            return embedding.tolist()
        else:
            # Fallback: simple hash-based embedding (not for production)
            return self._simple_embed(text)
    
    def _simple_embed(self, text: str) -> list[float]:
        """Simple embedding for demo purposes."""
        # Hash-based embedding (deterministic but not semantic)
        import hashlib
        
        hash_bytes = hashlib.sha256(text.encode()).digest()
        
        # Expand to embedding_dim
        embedding = []
        for i in range(self.embedding_dim):
            idx = i % len(hash_bytes)
            val = (hash_bytes[idx] / 255.0) * 2 - 1  # Normalize to [-1, 1]
            embedding.append(val)
        
        return embedding
    
    async def index(self, id: UUID, embedding: list[float], metadata: dict) -> None:
        """Index an embedding."""
        self._vectors[id] = np.array(embedding)
        self._metadata[id] = metadata
    
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[tuple[UUID, float]]:
        """Search for similar embeddings using cosine similarity."""
        if not self._vectors:
            return []
        
        query_vec = np.array(query_embedding)
        
        # Calculate cosine similarity
        results = []
        for id, vec in self._vectors.items():
            # Apply filters
            if filters:
                metadata = self._metadata.get(id, {})
                match = True
                for key, value in filters.items():
                    if metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            
            # Cosine similarity
            similarity = self._cosine_similarity(query_vec, vec)
            results.append((id, similarity))
        
        # Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    async def delete(self, id: UUID) -> bool:
        """Delete an embedding."""
        if id in self._vectors:
            del self._vectors[id]
            del self._metadata[id]
            return True
        return False
    
    async def get_stats(self) -> dict:
        """Get store statistics."""
        return {
            "total_vectors": len(self._vectors),
            "embedding_dim": self.embedding_dim,
        }


class QdrantVectorStore(VectorStore):
    """Qdrant-based vector store (for production).
    
    Requires qdrant-client to be installed.
    """
    
    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "nexusdev",
        embedding_dim: int = 384,
    ):
        """Initialize Qdrant store.
        
        Args:
            url: Qdrant server URL
            collection: Collection name
            embedding_dim: Dimension of embeddings
        """
        self.url = url
        self.collection = collection
        self.embedding_dim = embedding_dim
        self._client = None
        self._model = None

        try:
            from qdrant_client import QdrantClient

            if url == ":memory:":
                # qdrant-client local in-memory mode
                self._client = QdrantClient(path=":memory:")
            else:
                self._client = QdrantClient(url=url)
        except ImportError:
            pass

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            self._model = None

        if self._client:
            self._ensure_collection()
    
    def _ensure_collection(self) -> None:
        """Ensure collection exists."""
        if not self._client:
            return
        
        from qdrant_client.models import Distance, VectorParams
        
        collections = self._client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if self.collection not in collection_names:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
            )
    
    async def embed(self, text: str) -> list[float]:
        """Generate embedding."""
        if self._model:
            return self._model.encode(text).tolist()
        return self._simple_embed(text)

    def _simple_embed(self, text: str) -> list[float]:
        """Fallback embedding when sentence-transformers is unavailable."""
        import hashlib

        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding: list[float] = []
        for i in range(self.embedding_dim):
            idx = i % len(hash_bytes)
            val = (hash_bytes[idx] / 255.0) * 2 - 1
            embedding.append(val)
        return embedding
    
    async def index(self, id: UUID, embedding: list[float], metadata: dict) -> None:
        """Index an embedding."""
        if not self._client or not embedding:
            return
        
        from qdrant_client.models import PointStruct
        
        self._client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=str(id),
                    vector=embedding,
                    payload=metadata,
                )
            ],
        )
    
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[tuple[UUID, float]]:
        """Search for similar embeddings."""
        if not self._client or not query_embedding:
            return []

        query_filter = None
        if filters:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[
                    FieldCondition(key=key, match=MatchValue(value=value))
                    for key, value in filters.items()
                ]
            )

        if hasattr(self._client, "search"):
            results = self._client.search(
                collection_name=self.collection,
                query_vector=query_embedding,
                limit=top_k,
                query_filter=query_filter,
            )
        else:
            response = self._client.query_points(
                collection_name=self.collection,
                query=query_embedding,
                limit=top_k,
                query_filter=query_filter,
            )
            results = response.points

        parsed_results: list[tuple[UUID, float]] = []
        for item in results:
            try:
                parsed_results.append((UUID(str(item.id)), item.score))
            except (ValueError, TypeError):
                continue
        return parsed_results

    async def get_stats(self) -> dict[str, Any]:
        """Get store statistics."""
        if not self._client:
            return {
                "connected": False,
                "collection": self.collection,
                "embedding_dim": self.embedding_dim,
            }

        count = self._client.count(collection_name=self.collection, exact=True).count
        return {
            "connected": True,
            "collection": self.collection,
            "embedding_dim": self.embedding_dim,
            "total_vectors": count,
            "embedding_model_loaded": self._model is not None,
        }
