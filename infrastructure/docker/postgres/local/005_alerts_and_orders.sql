-- ============================================
-- VEDA AI — Alerts and maintenance (work) orders
-- Used by /api/alerts/status and /api/maintenance/orders (dashboard).
-- These tables were missing from the schema files, so a fresh install
-- returned 500 on those panels. Safe to run more than once.
-- Apply with: psql "$DATABASE_URL" -f infrastructure/docker/postgres/local/005_alerts_and_orders.sql
-- ============================================

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    severity VARCHAR(20) DEFAULT 'info' CHECK (severity IN ('critical', 'warning', 'info')),
    category VARCHAR(100),
    equipment_tag VARCHAR(100),
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS maintenance_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_number VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    equipment_tag VARCHAR(100),
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'completed', 'cancelled')),
    tolerances JSONB DEFAULT '{}',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_maintenance_tenant ON maintenance_orders(tenant_id);
