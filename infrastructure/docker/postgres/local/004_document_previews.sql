-- ============================================
-- VEDA AI — Document previews
-- Structured previews of Word, Excel and PowerPoint uploads (built by the
-- ingestion worker) so the upload page can show them. Safe to run more than once.
-- Apply with: psql "$DATABASE_URL" -f infrastructure/docker/postgres/local/004_document_previews.sql
-- ============================================

CREATE TABLE IF NOT EXISTS document_previews (
    document_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    preview JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_previews_tenant ON document_previews(tenant_id);
