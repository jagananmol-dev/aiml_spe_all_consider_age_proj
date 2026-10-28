-- ============================================
-- VEDA AI — Hosted mode (Vercel + Supabase + your own PC)
--
-- document_files: the bytes of each upload, for STORAGE_BACKEND=db. A
--   serverless web app has no disk the worker could read, so the file is
--   stored next to its documents row and goes with it on delete.
-- compute_node: one row the web app and scripts/compute-node.js use to
--   meet. The web app stamps wanted_at while someone is using the site; the
--   agent on the PC opens a tunnel when it sees that, writes the tunnel's
--   address, and closes it again once nobody has been active for a while.
--
-- Safe to run more than once.
-- Apply with: psql "$DATABASE_URL" -f infrastructure/docker/postgres/local/006_hosted_mode.sql
-- ============================================

CREATE TABLE IF NOT EXISTS document_files (
    document_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    data BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_files_tenant ON document_files(tenant_id);

CREATE TABLE IF NOT EXISTS compute_node (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Last time a signed-in user was active on the site
    wanted_at TIMESTAMPTZ,
    -- Public address of the PC's intelligence service while the tunnel is open
    tunnel_url TEXT,
    -- Last time the agent confirmed the tunnel is up
    seen_at TIMESTAMPTZ
);

INSERT INTO compute_node (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
