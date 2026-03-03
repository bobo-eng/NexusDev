"""Graph store for relationship-based retrieval.

Supports:
- Node and edge storage
- Graph traversal
- Relationship queries
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphNode:
    """Node in the knowledge graph."""

    id: str
    label: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """Edge in the knowledge graph."""

    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


class GraphStore(ABC):
    """Abstract graph store interface."""

    @abstractmethod
    async def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        pass

    @abstractmethod
    async def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph."""
        pass

    @abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
    ) -> list[GraphNode]:
        """Get neighboring nodes."""
        pass

    @abstractmethod
    async def traverse(
        self,
        start_id: str,
        max_depth: int = 3,
    ) -> list[list[GraphNode]]:
        """Traverse graph from starting node."""
        pass


class SimpleGraphStore(GraphStore):
    """Simple in-memory graph store.

    For production, replace with Neo4j or similar.
    """

    def __init__(self):
        """Initialize graph store."""
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = {}  # source -> edges
        self._incoming: dict[str, list[GraphEdge]] = {}  # target -> edges

    async def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        self._nodes[node.id] = node

    async def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph."""
        if edge.source not in self._edges:
            self._edges[edge.source] = []
        self._edges[edge.source].append(edge)

        if edge.target not in self._incoming:
            self._incoming[edge.target] = []
        self._incoming[edge.target].append(edge)

    async def get_node(self, node_id: str) -> GraphNode | None:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
    ) -> list[GraphNode]:
        """Get neighboring nodes."""
        edges = self._edges.get(node_id, [])

        neighbors = []
        for edge in edges:
            if edge_type and edge.type != edge_type:
                continue

            node = self._nodes.get(edge.target)
            if node:
                neighbors.append(node)

        return neighbors

    async def traverse(
        self,
        start_id: str,
        max_depth: int = 3,
    ) -> list[list[GraphNode]]:
        """Traverse graph from starting node (BFS)."""
        if start_id not in self._nodes:
            return []

        visited = {start_id}
        levels = [[self._nodes[start_id]]]
        current_level = [start_id]

        for depth in range(max_depth):
            next_level = []
            next_nodes = []

            for node_id in current_level:
                edges = self._edges.get(node_id, [])
                for edge in edges:
                    if edge.target not in visited:
                        visited.add(edge.target)
                        next_level.append(edge.target)
                        node = self._nodes.get(edge.target)
                        if node:
                            next_nodes.append(node)

            if not next_nodes:
                break

            levels.append(next_nodes)
            current_level = next_level

        return levels

    async def find_path(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
    ) -> list[GraphNode] | None:
        """Find path between two nodes (BFS)."""
        if start_id not in self._nodes or end_id not in self._nodes:
            return None

        from collections import deque

        queue = deque([(start_id, [start_id])])
        visited = {start_id}

        while queue:
            node_id, path = queue.popleft()

            if node_id == end_id:
                return [self._nodes[id] for id in path]

            if len(path) >= max_depth:
                continue

            edges = self._edges.get(node_id, [])
            for edge in edges:
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge.target]))

        return None

    async def get_code_dependencies(
        self,
        file_id: str,
    ) -> dict[str, list[str]]:
        """Get code dependencies for a file.

        Returns:
            Dict of {dependency_type: [file_ids]}
        """
        edges = self._edges.get(file_id, [])

        deps = {
            "imports": [],
            "calls": [],
            "inherits": [],
        }

        for edge in edges:
            if edge.type in deps:
                deps[edge.type].append(edge.target)

        return deps

    async def build_code_graph(
        self,
        files: list[dict],
    ) -> None:
        """Build code dependency graph from file analysis.

        Args:
            files: List of {id, path, imports, calls, inherits}
        """
        # Add file nodes
        for file in files:
            node = GraphNode(
                id=file["id"],
                label=file["path"],
                type="file",
                properties={"path": file["path"]},
            )
            await self.add_node(node)

        # Add dependency edges
        for file in files:
            for dep_type in ["imports", "calls", "inherits"]:
                for target_id in file.get(dep_type, []):
                    edge = GraphEdge(
                        source=file["id"],
                        target=target_id,
                        type=dep_type,
                    )
                    await self.add_edge(edge)

    async def get_stats(self) -> dict:
        """Get graph statistics."""
        return {
            "node_count": len(self._nodes),
            "edge_count": sum(len(edges) for edges in self._edges.values()),
        }


class Neo4jGraphStore(GraphStore):
    """Neo4j-based graph store (for production).

    Requires neo4j driver to be installed.
    """

    def __init__(
        self, uri: str = "bolt://localhost:7687", user: str = "neo4j", password: str = "password"
    ):
        """Initialize Neo4j store."""
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        except ImportError:
            pass

    async def add_node(self, node: GraphNode) -> None:
        """Add a node."""
        if not self._driver:
            return

        with self._driver.session() as session:
            session.run(
                "MERGE (n:Node {id: $id}) SET n.label = $label, n.type = $type, n += $props",
                id=node.id,
                label=node.label,
                type=node.type,
                props=node.properties,
            )

    async def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge."""
        if not self._driver:
            return

        with self._driver.session() as session:
            session.run(
                """
                MATCH (a:Node {id: $source}), (b:Node {id: $target})
                MERGE (a)-[r:RELATES {type: $type}]->(b)
                SET r += $props
                """,
                source=edge.source,
                target=edge.target,
                type=edge.type,
                props=edge.properties,
            )

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
    ) -> list[GraphNode]:
        """Get neighboring nodes."""
        if not self._driver:
            return []

        with self._driver.session() as session:
            if edge_type:
                result = session.run(
                    """
                    MATCH (n:Node {id: $id})-[r:RELATES {type: $type}]->(m:Node)
                    RETURN m.id as id, m.label as label, m.type as type, properties(m) as props
                    """,
                    id=node_id,
                    type=edge_type,
                )
            else:
                result = session.run(
                    """
                    MATCH (n:Node {id: $id})-[:RELATES]->(m:Node)
                    RETURN m.id as id, m.label as label, m.type as type, properties(m) as props
                    """,
                    id=node_id,
                )

            return [
                GraphNode(
                    id=record["id"],
                    label=record["label"],
                    type=record["type"],
                    properties=record["props"],
                )
                for record in result
            ]

    async def traverse(
        self,
        start_id: str,
        max_depth: int = 3,
    ) -> list[list[GraphNode]]:
        """Traverse graph."""
        if not self._driver:
            return []

        with self._driver.session() as session:
            result = session.run(
                """
                MATCH path = (start:Node {id: $id})-[:RELATES*1..$depth]->(end:Node)
                RETURN path
                LIMIT 100
                """,
                id=start_id,
                depth=max_depth,
            )

            # Process paths into levels
            levels = [[] for _ in range(max_depth + 1)]

            for record in result:
                path = record["path"]
                for i, node in enumerate(path.nodes):
                    if i < len(levels):
                        graph_node = GraphNode(
                            id=node["id"],
                            label=node["label"],
                            type=node["type"],
                            properties=dict(node),
                        )
                        if graph_node not in levels[i]:
                            levels[i].append(graph_node)

            return levels
