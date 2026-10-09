-- ============================================
-- VEDA AI — Local mode chunk store
-- For machines without pgvector (e.g. Windows PostgreSQL from init_local.sql).
-- Embeddings are stored as REAL[] and ranked by cosine similarity in the
-- intelligence service. Safe to run more than once.
-- Apply with: psql "$DATABASE_URL" -f infrastructure/docker/postgres/local/002_document_chunks.sql
-- ============================================

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding REAL[] NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant ON document_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document ON document_chunks(document_id);
