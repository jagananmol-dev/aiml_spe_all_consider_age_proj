"""
VEDA AI — Intelligence Service API

FastAPI application that exposes the intelligence engine:
- /query/prepare — Prepare graph-enriched chunks for LLM (primary endpoint)
- /query — Alias for /query/prepare (backwards compatible)
- /documents/index — Chunk + embed a parsed document (local mode)
- /entities/extract — Entity extraction from text
- /graph/search — Knowledge graph traversal
- /graph/stats — Knowledge graph statistics
- /health — Service health check
"""

import asyncio
import hmac
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from starlette.responses import Response

from .entity_extraction.extractor import extractor
from .knowledge_graph import local_graph
from .knowledge_graph.graph_manager import MAX_HOPS_LIMIT, KnowledgeGraphManager
from .rag.local_store import DocumentNotFoundError
from .rag.pipeline import rag_pipeline
from .rag.pipeline import settings as rag_settings

logger = logging.getLogger("veda.intelligence.api")

# ── Metrics ───────────────────────────────────────────
QUERY_COUNT = Counter("veda_queries_total", "Total RAG queries", ["tenant_id", "status"])
QUERY_LATENCY = Histogram("veda_query_latency_seconds", "RAG query latency")
ENTITY_COUNT = Counter("veda_entities_extracted_total", "Total entities extracted", ["entity_type"])


# ── Caller authentication ─────────────────────────────
_warned_missing_key = False


def require_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
) -> str:
    """
    Authenticate the caller and return the validated tenant id.

    The tenant id is trusted only because the caller is the web app, which
    derives it from a verified session. When INTERNAL_API_KEY is set, every
    request must present it; without it, anyone who can reach this port
    could query any tenant.
    """
    global _warned_missing_key
    expected_key = os.environ.get("INTERNAL_API_KEY")
    if expected_key:
        if not x_internal_key or not hmac.compare_digest(x_internal_key, expected_key):
            raise HTTPException(status_code=401, detail="Invalid internal API key")
    elif not _warned_missing_key:
        logger.warning("INTERNAL_API_KEY is not set — accepting unauthenticated requests")
        _warned_missing_key = True

    try:
        return str(uuid.UUID(x_tenant_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a UUID") from None


def _database_url() -> str:
    # Use env config — NEVER hardcode credentials in application code
    return os.environ.get("VEDA_DATABASE_URL", "postgresql://veda:changeme@localhost:5432/veda_db")


# ── Request/Response Models ───────────────────────────
class QueryRequest(BaseModel):
    query: str
    filters: dict | None = None  # Optional: document_type, date_range, equipment


class ChunkResponse(BaseModel):
    """A single prepared chunk in the response."""

    text: str
    source_type: str
    relevance_score: float
    document_id: str
    metadata: dict
    token_estimate: int
    entities_in_chunk: list[dict]
    graph_context: list[dict]


class PreparedContextResponse(BaseModel):
    """Response containing everything a paid LLM needs."""

    query: str
    chunks: list[ChunkResponse]
    graph_context: list[dict]
    system_prompt: str
    formatted_prompt: str
    total_token_estimate: int
    entities_found: list[dict]
    retrieval_metadata: dict


class EntityExtractionRequest(BaseModel):
    text: str
    page_number: int | None = None


class EntityExtractionResponse(BaseModel):
    entities: list[dict]
    count: int
    processing_time_ms: int


class IndexDocumentRequest(BaseModel):
    document_id: uuid.UUID
    title: str = Field(default="", max_length=500)
    raw_text: str = Field(min_length=1)


class IndexDocumentResponse(BaseModel):
    document_id: str
    chunks_indexed: int
    processing_time_ms: int


class GraphSearchRequest(BaseModel):
    entity_value: str
    entity_type: str | None = None
    max_hops: int = Field(default=3, ge=1, le=MAX_HOPS_LIMIT)


class GraphSearchResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    total_nodes: int
    total_edges: int


class GraphStatsResponse(BaseModel):
    total_nodes: int
    total_edges: int
    entity_types: dict
    relationship_types: dict
    last_updated: str | None


# ── Application ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 VEDA Intelligence Service starting...")
    # Load the embedding model in the background so the API is up at once
    # and the first question does not wait for the model
    warm = asyncio.create_task(asyncio.to_thread(rag_pipeline.warm_up))

    def report(task: asyncio.Task) -> None:
        if task.exception():
            logger.warning(f"Embedding warm-up failed: {task.exception()}")

    warm.add_done_callback(report)
    yield
    logger.info("🛑 VEDA Intelligence Service shutting down...")


app = FastAPI(
    title="VEDA AI Intelligence Service",
    description="RAG Chunk Preparation, Entity Extraction, and Knowledge Graph API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ─────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "veda-intelligence",
        "version": "0.2.0",
        "mode": "chunk-preparation",  # No LLM — returns prepared chunks
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")


@app.post("/query/prepare", response_model=PreparedContextResponse)
async def prepare_query_context(
    request: QueryRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    Prepare graph-enriched chunks for LLM consumption.

    This is the primary endpoint. It runs the full RAG pipeline:
    1. Embed the query
    2. Multi-retrieve (vector + graph + text)
    3. Fuse with RRF
    4. Enrich with knowledge graph context
    5. Return PreparedContext with chunks, prompt, and metadata

    The response contains everything a paid LLM needs to generate an answer.
    The caller (frontend or LLM integration layer) sends the formatted_prompt
    to their chosen LLM provider.
    """
    start = time.time()

    try:
        prepared = await rag_pipeline.prepare(
            query=request.query,
            tenant_id=x_tenant_id,
        )

        QUERY_COUNT.labels(tenant_id=x_tenant_id, status="success").inc()
        QUERY_LATENCY.observe(time.time() - start)

        return PreparedContextResponse(
            query=prepared.query,
            chunks=[
                ChunkResponse(
                    text=chunk.text,
                    source_type=chunk.source_type,
                    relevance_score=chunk.relevance_score,
                    document_id=chunk.document_id,
                    metadata=chunk.metadata,
                    token_estimate=chunk.token_estimate,
                    entities_in_chunk=chunk.entities_in_chunk,
                    graph_context=chunk.graph_context,
                )
                for chunk in prepared.chunks
            ],
            graph_context=prepared.graph_context,
            system_prompt=prepared.system_prompt,
            formatted_prompt=prepared.formatted_prompt,
            total_token_estimate=prepared.total_token_estimate,
            entities_found=prepared.entities_found,
            retrieval_metadata=prepared.retrieval_metadata,
        )
    except Exception as e:
        QUERY_COUNT.labels(tenant_id=x_tenant_id, status="error").inc()
        logger.exception("Query preparation failed")
        raise HTTPException(status_code=500, detail="Internal error") from e


@app.post("/query", response_model=PreparedContextResponse)
async def query_knowledge_base(
    request: QueryRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    Alias for /query/prepare — backwards compatible endpoint.

    Returns the same PreparedContext. When a paid LLM is configured,
    this endpoint can be updated to also return the LLM answer.
    """
    return await prepare_query_context(request, x_tenant_id)


@app.post("/documents/index", response_model=IndexDocumentResponse)
async def index_document(
    request: IndexDocumentRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    Chunk, embed, and store a parsed document (local mode), then mark it indexed.

    Called by the local ingestion worker in place of the Kafka pipeline. The
    document must belong to the calling tenant.
    """
    start = time.time()
    try:
        count = await rag_pipeline.index_document(
            tenant_id=x_tenant_id,
            document_id=str(request.document_id),
            title=request.title,
            raw_text=request.raw_text,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Indexing failed for document {request.document_id}")
        raise HTTPException(status_code=500, detail="Internal error") from e

    return IndexDocumentResponse(
        document_id=str(request.document_id),
        chunks_indexed=count,
        processing_time_ms=int((time.time() - start) * 1000),
    )


@app.post("/entities/extract", response_model=EntityExtractionResponse)
async def extract_entities(
    request: EntityExtractionRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """Extract industrial entities from text."""
    start = time.time()

    entities = extractor.extract_entities(
        text=request.text,
        page_number=request.page_number,
    )

    # Track metrics
    for entity in entities:
        ENTITY_COUNT.labels(entity_type=entity.entity_type).inc()

    processing_time_ms = int((time.time() - start) * 1000)

    return EntityExtractionResponse(
        entities=[
            {
                "type": e.entity_type,
                "value": e.value,
                "normalized_value": e.normalized_value,
                "confidence": e.confidence,
                "start_offset": e.start_offset,
                "end_offset": e.end_offset,
                "page_number": e.page_number,
                "attributes": e.attributes,
            }
            for e in entities
        ],
        count=len(entities),
        processing_time_ms=processing_time_ms,
    )


@app.post("/graph/search", response_model=GraphSearchResponse)
async def search_knowledge_graph(
    request: GraphSearchRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    Search the knowledge graph for an entity and its connections.
    Returns nodes and edges for visualization.
    """
    try:
        if rag_settings.graph_backend == "local":
            results = await asyncio.to_thread(
                local_graph.search,
                _database_url(),
                x_tenant_id,
                request.entity_value,
                request.entity_type,
                request.max_hops,
            )
        else:
            results = await KnowledgeGraphManager(_database_url()).get_entity_context(
                tenant_id=x_tenant_id,
                entity_value=request.entity_value,
                entity_type=request.entity_type,
                max_hops=request.max_hops,
            )

        # Convert to node/edge format for visualization
        nodes = []
        edges = []
        seen_nodes = set()

        for result in results:
            source_id = result["source_value"]
            target_id = result["target_value"]

            if source_id not in seen_nodes:
                nodes.append(
                    {
                        "id": source_id,
                        "label": result["source_value"],
                        "type": result["source_type"],
                    }
                )
                seen_nodes.add(source_id)

            if target_id not in seen_nodes:
                nodes.append(
                    {
                        "id": target_id,
                        "label": result["target_value"],
                        "type": result["target_type"],
                    }
                )
                seen_nodes.add(target_id)

            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "relationship": result.get("relationship", "RELATED_TO"),
                    "distance": result["distance"],
                }
            )

        return GraphSearchResponse(
            nodes=nodes,
            edges=edges,
            total_nodes=len(nodes),
            total_edges=len(edges),
        )

    except Exception as e:
        logger.exception("Graph search failed")
        raise HTTPException(status_code=500, detail="Internal error") from e


class GraphOverviewRequest(BaseModel):
    limit: int = Field(default=2000, ge=1, le=5000)


@app.post("/graph/overview")
async def graph_overview(
    request: GraphOverviewRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    The tenant's whole knowledge graph (nodes and edges) for visualisation.
    Only the local graph backend supports this; AGE returns 501.
    """
    if rag_settings.graph_backend != "local":
        raise HTTPException(status_code=501, detail="Graph overview needs VEDA_GRAPH_BACKEND=local")
    try:
        return await asyncio.to_thread(
            local_graph.overview, _database_url(), x_tenant_id, request.limit
        )
    except Exception as e:
        logger.exception("Graph overview failed")
        raise HTTPException(status_code=500, detail="Internal error") from e


class GraphFindingsRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=1000)


@app.post("/graph/findings")
async def graph_findings(
    request: GraphFindingsRequest,
    x_tenant_id: str = Depends(require_tenant),
):
    """
    What the tenant's documents say about each asset: the issues, actions and
    values the graph links to it, with source documents. Derived from the
    uploads (Maintenance Intel), so it needs the local graph backend.
    """
    if rag_settings.graph_backend != "local":
        raise HTTPException(status_code=501, detail="Graph findings need VEDA_GRAPH_BACKEND=local")
    try:
        schema = await asyncio.to_thread(local_graph.tenant_schema, _database_url(), x_tenant_id)
        items = await asyncio.to_thread(
            local_graph.findings, _database_url(), x_tenant_id, schema, request.limit
        )
        return {"findings": items, "types": schema.public_types()}
    except Exception as e:
        logger.exception("Graph findings failed")
        raise HTTPException(status_code=500, detail="Internal error") from e


@app.get("/graph/stats", response_model=GraphStatsResponse)
async def get_graph_statistics(
    x_tenant_id: str = Depends(require_tenant),
):
    """
    Get knowledge graph statistics for monitoring.
    Shows node/edge counts, entity type distribution, and last update time.
    """
    if rag_settings.graph_backend == "local":
        stats = await asyncio.to_thread(local_graph.stats, _database_url(), x_tenant_id)
    else:
        stats = await KnowledgeGraphManager(_database_url()).get_graph_stats(x_tenant_id)

    return GraphStatsResponse(
        total_nodes=stats["total_nodes"],
        total_edges=stats["total_edges"],
        entity_types=stats["entity_types"],
        relationship_types=stats["relationship_types"],
        last_updated=stats["last_updated"],
    )


# ── Entry Point ──────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "src.api:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
    )
