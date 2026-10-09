-- ============================================
-- VEDA AI — Local mode knowledge graph
-- For machines without Apache AGE (e.g. Windows PostgreSQL from init_local.sql).
-- Used when VEDA_GRAPH_BACKEND=local. Safe to run more than once.
-- Apply with: psql "$DATABASE_URL" -f infrastructure/docker/postgres/local/003_local_graph.sql
-- ============================================

CREATE TABLE IF NOT EXISTS graph_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    entity_type VARCHAR(50) NOT NULL,
    normalized_value TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, entity_type, normalized_value)
);

-- One row per edge per source document, so re-indexing or deleting a
-- document replaces or removes exactly the edges it contributed
CREATE TABLE IF NOT EXISTS graph_edges (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relationship VARCHAR(50) NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (document_id, source_id, target_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_tenant ON graph_nodes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_tenant ON graph_edges(tenant_id);
