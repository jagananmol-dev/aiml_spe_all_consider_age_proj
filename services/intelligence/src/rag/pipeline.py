"""
VEDA AI — RAG Pipeline (Chunk Preparation Mode)

Multi-retrieval pipeline that combines:
1. Vector search (pgvector) — semantic similarity
2. Graph traversal (Apache AGE) — structural relationships
3. Full-text search (OpenSearch) — keyword matching
4. Metadata filtering — time range, equipment, document type

Uses Reciprocal Rank Fusion (RRF) to merge and re-rank results from all sources.

NOTE: This pipeline does NOT call an LLM. It prepares structured, graph-enriched
chunks ready for any paid LLM to consume. The LLM integration point is the
PreparedContext object returned by prepare().
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
import numpy as np
import psycopg
from pydantic_settings import BaseSettings
from sentence_transformers import SentenceTransformer

from ..entity_extraction import semantic
from ..entity_extraction.schema import get_schema
from ..knowledge_graph import local_graph
from ..knowledge_graph.chunk_builder import (
    ChunkBuilder,
    PreparedChunk,
    PreparedContext,
)
from ..knowledge_graph.graph_manager import KnowledgeGraphManager
from ..knowledge_graph.relationships import document_edges, infer_relationships
from . import local_store

logger = logging.getLogger("veda.intelligence.rag")


class RAGSettings(BaseSettings):
    database_url: str = "postgresql://veda:changeme@localhost:5432/veda_db"
    opensearch_url: str = "http://localhost:9200"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Retrieval parameters
    vector_top_k: int = 15
    graph_max_hops: int = 3
    text_top_k: int = 10
    rrf_k: int = 60  # RRF constant
    final_top_k: int = 8  # Final results after fusion
    # Local backend: drop passages below this cosine similarity. With
    # all-MiniLM-L6-v2, relevant passages score ~0.35+ and unrelated ~0.2.
    min_similarity: float = 0.25
    # When nothing clears min_similarity, return this many closest passages
    # flagged as a weak match, so the model can still answer or say what is missing
    fallback_top_k: int = 3

    # Chunk preparation
    max_chunk_tokens: int = 12000  # Max tokens across all chunks
    max_chunk_size: int = 1500  # Characters per stored chunk
    chunk_overlap: int = 200

    # Backends — "local" mode needs only PostgreSQL (no pgvector/AGE/OpenSearch)
    vector_backend: str = "pgvector"  # "pgvector" | "local"
    graph_enabled: bool = True
    # Where the knowledge graph lives: "age" (Apache AGE) | "local" (plain
    # PostgreSQL tables, built when documents are indexed in local mode)
    graph_backend: str = "age"
    # Local graph backend: question phrases are linked to graph nodes by
    # embedding, and passages naming a linked entity in a document the graph
    # ties to it gain this much similarity (0 turns it off)
    graph_retrieval_boost: float = 0.05
    opensearch_enabled: bool = True

    class Config:
        env_prefix = "VEDA_"


settings = RAGSettings()


def tenant_index_suffix(tenant_id: str) -> str:
    """
    Return a tenant id that is safe to embed in an OpenSearch index URL.

    Tenant ids are UUIDs; anything else is rejected so a crafted id can't
    traverse to another index or API path.
    """
    return str(uuid.UUID(str(tenant_id)))


# ── Data Models ───────────────────────────────────────
@dataclass
class RetrievedChunk:
    """A chunk of text retrieved from any source."""

    document_id: str
    chunk_text: str
    score: float
    source: str  # "vector", "graph", "text", "metadata"
    metadata: dict | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class RAGPipeline:
    """
    Multi-retrieval RAG pipeline with Graph-Augmented retrieval.

    The key innovation is combining vector similarity with knowledge graph
    traversal — so a query about PUMP-101 returns not just text mentioning
    the pump, but also connected systems, upstream failures, governing
    procedures, and responsible personnel.

    This pipeline PREPARES context for an LLM — it does not call one.
    """

    def __init__(self):
        self._embedding_model = None
        self._graph_manager = None
        self._chunk_builder = None

    @property
    def embedding_model(self) -> SentenceTransformer:
        """Lazy-load the embedding model."""
        if self._embedding_model is None:
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            model = SentenceTransformer(settings.embedding_model)
            # The knowledge graph types and links entities with this same
            # model (no second model in memory), batched and cached per phrase
            semantic.set_encoder(
                lambda texts: model.encode(
                    texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
                )
            )
            self._embedding_model = model
        return self._embedding_model

    @property
    def graph_manager(self) -> KnowledgeGraphManager:
        """Lazy-load the graph manager."""
        if self._graph_manager is None:
            self._graph_manager = KnowledgeGraphManager(settings.database_url)
        return self._graph_manager

    @property
    def chunk_builder(self) -> ChunkBuilder:
        """Lazy-load the chunk builder."""
        if self._chunk_builder is None:
            self._chunk_builder = ChunkBuilder(max_total_tokens=settings.max_chunk_tokens)
        return self._chunk_builder

    def warm_up(self) -> None:
        """
        Load the embedding model and run one encode, so the first user
        question does not pay the ~10 s model load.
        """
        started = time.time()
        self.embedding_model.encode("warm up", normalize_embeddings=True)
        logger.info(f"Embedding model ready in {time.time() - started:.1f}s")
        if settings.vector_backend == "local":
            tenants = local_store.preload_all(settings.database_url)
            logger.info(f"Search index loaded for {tenants} tenant(s)")

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a query string."""
        embedding = self.embedding_model.encode(query, normalize_embeddings=True)
        return embedding.tolist()

    async def retrieve_vector(
        self,
        query_embedding: list[float],
        tenant_id: str,
        top_k: int | None = None,
        stats: dict | None = None,
        boost: dict[str, set[str]] | None = None,
    ) -> list[RetrievedChunk]:
        """
        Vector similarity search using pgvector.
        Uses cosine distance for semantic matching. When `stats` is given, the
        local backend fills in how many chunks and documents were searched.
        """
        top_k = top_k or settings.vector_top_k

        if settings.vector_backend == "local":
            return await self.retrieve_vector_local(query_embedding, tenant_id, top_k, stats, boost)

        async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
            # Set tenant context for RLS
            await conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])

            # pgvector cosine similarity search
            embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

            rows = await conn.execute(
                """
                SELECT
                    de.document_id,
                    de.chunk_text,
                    de.chunk_metadata,
                    1 - (de.embedding <=> %s::vector) as similarity
                FROM document_embeddings de
                JOIN documents d ON de.document_id = d.id AND d.tenant_id = de.tenant_id
                WHERE de.tenant_id = %s
                  AND d.status = 'indexed'
                ORDER BY de.embedding <=> %s::vector
                LIMIT %s
                """,
                [embedding_str, tenant_id, embedding_str, top_k],
            )

            chunks = []
            async for row in rows:
                chunks.append(
                    RetrievedChunk(
                        document_id=str(row[0]),
                        chunk_text=row[1],
                        score=float(row[3]),
                        source="vector",
                        metadata=row[2] if row[2] else {},
                    )
                )

            return chunks

    async def retrieve_vector_local(
        self,
        query_embedding: list[float],
        tenant_id: str,
        top_k: int,
        stats: dict | None = None,
        boost: dict[str, set[str]] | None = None,
    ) -> list[RetrievedChunk]:
        """Vector search over the local chunk store (no pgvector)."""
        rows, search_stats = await asyncio.to_thread(
            local_store.search_chunks_with_stats,
            settings.database_url,
            tenant_id,
            query_embedding,
            top_k,
            settings.min_similarity,
            settings.fallback_top_k,
            boost,
            settings.graph_retrieval_boost,
        )
        if stats is not None:
            stats.update(search_stats)
        return [
            RetrievedChunk(
                document_id=row["document_id"],
                chunk_text=row["chunk_text"],
                score=row["score"],
                source="vector",
                metadata=row["metadata"],
            )
            for row in rows
        ]

    async def index_document(
        self, tenant_id: str, document_id: str, title: str, raw_text: str
    ) -> int:
        """
        Chunk, embed, and store a parsed document in the local chunk store,
        then mark it indexed. Returns the number of chunks stored.
        """
        if settings.vector_backend != "local":
            raise RuntimeError("Direct indexing is only available with VEDA_VECTOR_BACKEND=local")

        builder = ChunkBuilder(
            max_chunk_size=settings.max_chunk_size, chunk_overlap=settings.chunk_overlap
        )
        chunks = builder.merge_small_chunks(
            builder.split_into_chunks(raw_text, document_id, metadata={"title": title})
        )
        if not chunks:
            raise ValueError("No text to index")

        # Embed each chunk with its document title so a passage keeps its context
        texts = [f"{title}\n\n{chunk.text}" if title else chunk.text for chunk in chunks]
        embeddings = await asyncio.to_thread(
            self.embedding_model.encode,
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        stored = [
            local_store.StoredChunk(
                text=chunk.text, embedding=list(vector), metadata=chunk.metadata
            )
            for chunk, vector in zip(chunks, embeddings)
        ]
        count = await asyncio.to_thread(
            local_store.replace_document_chunks,
            settings.database_url,
            tenant_id,
            document_id,
            stored,
        )

        if settings.graph_backend == "local":
            # The graph is an extra view of the document; failing to build it
            # must not undo a successful index
            try:
                await asyncio.to_thread(
                    self.build_local_graph, tenant_id, document_id, raw_text, title
                )
            except Exception as e:
                logger.warning(f"Knowledge graph update failed for document {document_id}: {e}")

        return count

    def build_local_graph(
        self,
        tenant_id: str,
        document_id: str,
        raw_text: str,
        title: str | None = None,
        doc=None,
        name_types: dict[str, str] | None = None,
    ) -> int:
        """
        Extract entities from a document with the tenant's graph schema and
        store its edges in the local graph: relations between entities, plus
        (with a title) the document's own node linked to what it mentions.
        New names close to an existing node's name join that node.
        """
        from ..entity_extraction.extractor import extractor

        _ = self.embedding_model  # registers the encoder used for entity typing
        schema = local_graph.tenant_schema(settings.database_url, tenant_id)
        known = local_graph.known_node_values(settings.database_url, tenant_id)
        entities = [
            {
                "entity_type": e.entity_type,
                "value": e.value,
                "normalized_value": e.normalized_value,
                "confidence": e.confidence,
                "start_offset": e.start_offset,
            }
            for e in extractor.extract_entities(
                raw_text, schema=schema, known_nodes=known, doc=doc, name_types=name_types
            )
        ]
        edges = infer_relationships(entities, raw_text, schema)
        if title:
            edges += document_edges(entities, title, schema)
        return local_graph.replace_document_graph(
            settings.database_url, tenant_id, document_id, edges
        )

    def retrieve_graph_local(
        self, query: str, query_entities: list, tenant_id: str
    ) -> tuple[list[dict], dict]:
        """
        Link the question to the tenant's graph and walk from the linked nodes.

        The question's entities and key phrases are matched to node names
        exactly or by embedding (one batched, cached encode and one matrix
        product against the tenant's cached node matrix). Returns the walked
        edges and {document_id: entity names}, used to boost those documents'
        passages that name the entities.
        """
        schema = local_graph.tenant_schema(settings.database_url, tenant_id)
        phrases = [e.normalized_value for e in query_entities]
        phrases += [c.phrase for c in semantic.candidate_phrases(query, limit=12)]
        phrases = list(dict.fromkeys(p for p in phrases if p))
        threshold = float(schema.semantic.get("query_link_similarity", 0.78))
        linked = local_graph.link_phrases(settings.database_url, tenant_id, phrases, threshold)
        edges = local_graph.search_many(
            settings.database_url, tenant_id, linked, max_hops=2, limit=30, schema=schema
        )

        names = {n["normalized_value"].lower() for n in linked}
        boost: dict[str, set[str]] = {}
        for edge in edges:
            if edge.get("document_id"):
                for value in (edge["source_value"], edge["target_value"]):
                    if value.lower() in names:
                        boost.setdefault(edge["document_id"], set()).add(value.lower())
        return edges, boost

    async def retrieve_graph(
        self,
        entities: list[str],
        entity_types: list[str],
        tenant_id: str,
        max_hops: int | None = None,
    ) -> tuple[list[RetrievedChunk], list[dict]]:
        """
        Graph traversal using Apache AGE via KnowledgeGraphManager.
        Finds related entities and their connected documents.

        Returns:
            tuple of (chunks for RRF, raw graph context for enrichment)
        """
        max_hops = max_hops or settings.graph_max_hops
        chunks: list[RetrievedChunk] = []
        all_graph_context: list[dict] = []

        if not entities or not settings.graph_enabled:
            return chunks, all_graph_context

        try:
            conn_cm = await self.graph_manager._get_connection()
        except Exception as e:
            logger.warning(f"Knowledge graph unavailable, skipping graph retrieval: {e}")
            return chunks, all_graph_context

        async with conn_cm as conn:
            await self.graph_manager._set_tenant(conn, tenant_id)
            for entity_value, entity_type in zip(entities[:5], entity_types[:5]):
                try:
                    graph_results = await self.graph_manager.get_entity_context(
                        tenant_id=tenant_id,
                        entity_value=entity_value,
                        entity_type=entity_type,
                        max_hops=max_hops,
                        conn=conn,
                    )

                    all_graph_context.extend(graph_results)

                    for result in graph_results:
                        # Convert graph results to chunks with context
                        context = (
                            f"[Knowledge Graph] {result['source_type']}: {result['source_value']} "
                            f"is connected to {result['target_type']}: {result['target_value']} "
                            f"(distance: {result['distance']} hops)"
                        )

                        chunks.append(
                            RetrievedChunk(
                                document_id=result.get("document_id", ""),
                                chunk_text=context,
                                score=1.0 / (1 + result["distance"]),
                                source="graph",
                                metadata={
                                    "source_entity": result["source_value"],
                                    "related_entity": result["target_value"],
                                    "relationship_distance": result["distance"],
                                },
                            )
                        )

                except Exception as e:
                    logger.warning(f"Graph traversal failed for entity '{entity_value}': {e}")

        return chunks, all_graph_context

    async def retrieve_text(
        self, query: str, tenant_id: str, top_k: int | None = None
    ) -> list[RetrievedChunk]:
        """
        Full-text search using OpenSearch.
        Complements vector search for exact keyword matching
        (equipment tags, regulation numbers, etc.).
        """
        top_k = top_k or settings.text_top_k
        chunks: list[RetrievedChunk] = []

        if not settings.opensearch_enabled:
            return chunks

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.opensearch_url}/veda-documents-{tenant_index_suffix(tenant_id)}/_search",
                    json={
                        "query": {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    "title^3",
                                    "raw_text",
                                    "entities.value^2",
                                    "equipment_tags^2",
                                ],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                            }
                        },
                        "size": top_k,
                        "_source": ["document_id", "title", "raw_text", "chunk_text"],
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    hits = response.json().get("hits", {}).get("hits", [])
                    for hit in hits:
                        source = hit["_source"]
                        chunks.append(
                            RetrievedChunk(
                                document_id=source.get("document_id", hit["_id"]),
                                chunk_text=source.get("chunk_text", source.get("raw_text", ""))[
                                    :2000
                                ],
                                score=hit["_score"] / 100.0,  # Normalize score
                                source="text",
                                metadata={"title": source.get("title", "")},
                            )
                        )
        except Exception as e:
            logger.warning(f"OpenSearch query failed: {e}")

        return chunks

    def reciprocal_rank_fusion(
        self, result_lists: list[list[RetrievedChunk]], k: int | None = None
    ) -> list[RetrievedChunk]:
        """
        Reciprocal Rank Fusion (RRF) to merge results from multiple retrieval sources.

        RRF formula: score = Σ 1 / (k + rank_i)

        This gives equal weight to all retrieval methods while preferring documents
        that appear in multiple result lists.
        """
        k = k or settings.rrf_k

        # Calculate RRF scores
        doc_scores: dict[str, float] = {}
        doc_chunks: dict[str, RetrievedChunk] = {}

        for result_list in result_lists:
            for rank, chunk in enumerate(result_list):
                doc_key = f"{chunk.document_id}:{chunk.chunk_text[:100]}"
                rrf_score = 1.0 / (k + rank + 1)

                if doc_key in doc_scores:
                    doc_scores[doc_key] += rrf_score
                    # Keep the chunk with more context
                    if len(chunk.chunk_text) > len(doc_chunks[doc_key].chunk_text):
                        doc_chunks[doc_key] = chunk
                else:
                    doc_scores[doc_key] = rrf_score
                    doc_chunks[doc_key] = chunk

        # Sort by fused score
        sorted_keys = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)

        fused_results = []
        for key in sorted_keys[: settings.final_top_k]:
            chunk = doc_chunks[key]
            chunk.score = doc_scores[key]
            fused_results.append(chunk)

        return fused_results

    async def prepare(self, query: str, tenant_id: str) -> PreparedContext:
        """
        Execute the full RAG pipeline and return prepared context for LLM.

        Steps:
        1. Embed the query
        2. Extract entities from query for graph traversal
        3. Run multi-retrieval (vector + graph + text)
        4. Fuse results with RRF
        5. Build graph-enriched, token-budgeted chunks
        6. Return PreparedContext (NOT an LLM answer)

        The returned PreparedContext contains everything a paid LLM needs:
        - Ranked, deduplicated chunks with graph enrichment
        - System prompt tuned for industrial domain
        - Pre-formatted prompt string
        - Token budget information
        """
        start_time = time.time()

        # 1. Generate query embedding
        query_embedding = self.embed_query(query)

        # 2. Extract entities from query for graph traversal
        from ..entity_extraction.extractor import extractor

        query_entities = extractor.extract_entities(query, use_nlp=False)
        subjects = get_schema().subject_types
        entity_values = [e.normalized_value for e in query_entities if e.entity_type in subjects]
        entity_types = [e.entity_type for e in query_entities if e.entity_type in subjects]

        # 3. Multi-retrieval (vector + graph + text)
        search_stats: dict = {}
        boost: dict[str, set[str]] | None = None
        graph_results: list[RetrievedChunk] = []
        graph_context: list[dict] = []
        if settings.graph_backend == "local":
            # The local graph steers the vector search instead of adding
            # passages of its own, so every passage stays a real, citable one
            try:
                graph_context, boost = await asyncio.to_thread(
                    self.retrieve_graph_local, query, query_entities, tenant_id
                )
            except Exception as e:
                logger.warning(f"Local graph retrieval skipped: {e}")
        else:
            graph_results, graph_context = await self.retrieve_graph(
                entity_values, entity_types, tenant_id
            )
        vector_results = await self.retrieve_vector(
            query_embedding, tenant_id, stats=search_stats, boost=boost
        )
        text_results = await self.retrieve_text(query, tenant_id)

        logger.info(
            f"Retrieved: {len(vector_results)} vector, "
            f"{len(graph_results)} graph, {len(text_results)} text"
        )

        # 4. Fuse results with RRF
        fused_chunks = self.reciprocal_rank_fusion([vector_results, graph_results, text_results])

        # 5. Convert RetrievedChunks to PreparedChunks
        prepared_chunks = [
            PreparedChunk(
                text=chunk.chunk_text,
                source_type=chunk.source,
                relevance_score=chunk.score,
                document_id=chunk.document_id,
                metadata=chunk.metadata or {},
                token_estimate=self.chunk_builder.estimate_tokens(chunk.chunk_text),
            )
            for chunk in fused_chunks
        ]

        # 6. Build PreparedContext with graph enrichment
        entities_found = [
            {
                "entity_type": e.entity_type,
                "value": e.value,
                "normalized_value": e.normalized_value,
                "confidence": e.confidence,
            }
            for e in query_entities
        ]

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Calculate average confidence from retrieval scores
        avg_score = np.mean([c.score for c in fused_chunks]) if fused_chunks else 0

        prepared_context = self.chunk_builder.prepare_context(
            query=query,
            chunks=prepared_chunks,
            graph_context=graph_context,
            entities_found=entities_found,
            retrieval_metadata={
                "vector_results_count": len(vector_results),
                "graph_results_count": len(graph_results),
                "text_results_count": len(text_results),
                "fused_results_count": len(fused_chunks),
                "retrieval_latency_ms": elapsed_ms,
                "chunks_searched": search_stats.get("chunks_searched"),
                "documents_searched": search_stats.get("documents_searched"),
                "low_confidence": search_stats.get("low_confidence", False),
                "graph_facts_count": len(graph_context),
                "graph_boosted_chunks": search_stats.get("graph_boosted_chunks", 0),
                "confidence_score": round(min(avg_score * 100, 99), 1),
            },
        )

        logger.info(
            f"Prepared context: {len(prepared_context.chunks)} chunks, "
            f"{prepared_context.total_token_estimate} estimated tokens, "
            f"{elapsed_ms}ms"
        )

        return prepared_context


# Singleton
rag_pipeline = RAGPipeline()
