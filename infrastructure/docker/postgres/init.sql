-- ============================================
-- VEDA AI — PostgreSQL Initialization Script
-- Sets up: Apache AGE + pgvector + schemas + RLS
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- Trigram similarity for fuzzy search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- UUID generation

-- Load AGE into search path
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the knowledge graph
SELECT create_graph('veda_knowledge_graph');


-- ============================================
-- CORE SCHEMA
-- ============================================

-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    domain VARCHAR(255),
    logo_url TEXT,
    subscription_tier VARCHAR(50) NOT NULL DEFAULT 'starter',
    max_documents INTEGER NOT NULL DEFAULT 10000,
    max_users INTEGER NOT NULL DEFAULT 25,
    settings JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_slug ON tenants(slug);
CREATE INDEX idx_tenants_domain ON tenants(domain);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash TEXT,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    avatar_url TEXT,
    department VARCHAR(100),
    designation VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, email),
    CONSTRAINT valid_role CHECK (role IN ('admin', 'engineer', 'operator', 'auditor', 'viewer'))
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    uploaded_by UUID REFERENCES users(id),
    title VARCHAR(500) NOT NULL,
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100),
    storage_path TEXT NOT NULL,
    storage_bucket VARCHAR(255) NOT NULL,
    
    -- Processing pipeline status
    status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
    parsing_status VARCHAR(50) DEFAULT 'pending',
    extraction_status VARCHAR(50) DEFAULT 'pending',
    embedding_status VARCHAR(50) DEFAULT 'pending',
    
    -- Extracted metadata
    page_count INTEGER,
    word_count INTEGER,
    language VARCHAR(10),
    document_type VARCHAR(100),      -- e.g., 'P&ID', 'SOP', 'Work Order', 'Inspection Report'
    document_category VARCHAR(100),  -- e.g., 'Engineering', 'Maintenance', 'Safety', 'Quality'
    
    -- Content
    raw_text TEXT,
    parsed_content JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
    
    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    parent_document_id UUID REFERENCES documents(id),
    superseded_by UUID REFERENCES documents(id),
    is_latest BOOLEAN NOT NULL DEFAULT true,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_status CHECK (status IN ('uploaded', 'processing', 'parsing', 'parsed', 'extracting', 'extracted', 'embedding', 'indexed', 'failed', 'archived')),
    CONSTRAINT valid_parse_status CHECK (parsing_status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT valid_extract_status CHECK (extraction_status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT valid_embed_status CHECK (embedding_status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX idx_documents_tenant ON documents(tenant_id);
CREATE INDEX idx_documents_status ON documents(tenant_id, status);
CREATE INDEX idx_documents_type ON documents(tenant_id, document_type);
CREATE INDEX idx_documents_category ON documents(tenant_id, document_category);

-- Entities table — extracted from documents
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    
    entity_type VARCHAR(100) NOT NULL,  -- EQUIPMENT_TAG, PROCESS_PARAMETER, CHEMICAL, etc.
    entity_value TEXT NOT NULL,
    normalized_value TEXT,               -- Canonical/normalized form
    
    -- Position in document
    page_number INTEGER,
    start_offset INTEGER,
    end_offset INTEGER,
    
    -- Confidence
    confidence FLOAT NOT NULL DEFAULT 0.0,
    is_verified BOOLEAN NOT NULL DEFAULT false,
    verified_by UUID REFERENCES users(id),
    
    -- Additional metadata
    attributes JSONB NOT NULL DEFAULT '{}',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_entity_type CHECK (entity_type IN (
        'EQUIPMENT_TAG', 'PROCESS_PARAMETER', 'CHEMICAL', 'REGULATION',
        'PERSON', 'DATE', 'LOCATION', 'FAILURE_MODE', 'MAINTENANCE_ACTION',
        'SAFETY_CONDITION', 'MATERIAL', 'PROCEDURE', 'MEASUREMENT', 'OTHER'
    ))
);

CREATE INDEX idx_entities_tenant ON entities(tenant_id);
CREATE INDEX idx_entities_document ON entities(document_id);
CREATE INDEX idx_entities_type ON entities(tenant_id, entity_type);
CREATE INDEX idx_entities_value ON entities(tenant_id, entity_value);
CREATE INDEX idx_entities_normalized ON entities(tenant_id, normalized_value);

-- Document embeddings — for vector search (pgvector)
CREATE TABLE IF NOT EXISTS document_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_metadata JSONB NOT NULL DEFAULT '{}',
    
    embedding vector(384),  -- sentence-transformers/all-MiniLM-L6-v2 dimension
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_embeddings_tenant ON document_embeddings(tenant_id);
CREATE INDEX idx_embeddings_document ON document_embeddings(document_id);

-- Create HNSW index for fast vector similarity search
CREATE INDEX idx_embeddings_vector ON document_embeddings 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Conversations — Copilot chat history
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_tenant ON conversations(tenant_id);
CREATE INDEX idx_conversations_user ON conversations(user_id);

-- Messages — Individual chat messages
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    
    -- AI-specific fields
    confidence_score FLOAT,
    sources JSONB,               -- Array of source documents with page refs
    related_entities JSONB,      -- Entities mentioned in the response
    model_used VARCHAR(100),
    latency_ms INTEGER,
    tokens_used INTEGER,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);

-- Maintenance records
CREATE TABLE IF NOT EXISTS maintenance_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id),
    
    record_type VARCHAR(50) NOT NULL,  -- 'work_order', 'inspection', 'failure', 'calibration'
    record_number VARCHAR(100),
    equipment_tag VARCHAR(200),
    
    description TEXT,
    root_cause TEXT,
    corrective_action TEXT,
    
    severity VARCHAR(20),
    priority VARCHAR(20),
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    
    scheduled_date DATE,
    completed_date DATE,
    assigned_to UUID REFERENCES users(id),
    
    cost_estimate DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    downtime_hours DECIMAL(10,2),
    
    metadata JSONB NOT NULL DEFAULT '{}',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_maintenance_tenant ON maintenance_records(tenant_id);
CREATE INDEX idx_maintenance_equipment ON maintenance_records(tenant_id, equipment_tag);
CREATE INDEX idx_maintenance_type ON maintenance_records(tenant_id, record_type);

-- Compliance rules — regulatory requirements
CREATE TABLE IF NOT EXISTS compliance_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    
    regulation_name VARCHAR(255) NOT NULL,    -- e.g., 'OISD-154', 'Factory Act 1948'
    regulation_version VARCHAR(50),
    section_reference VARCHAR(100),
    
    requirement_text TEXT NOT NULL,
    requirement_type VARCHAR(50),              -- 'mandatory', 'recommended', 'informational'
    
    applicable_equipment_types TEXT[],
    applicable_document_types TEXT[],
    
    evidence_status VARCHAR(50) DEFAULT 'unmapped',
    evidence_document_ids UUID[],
    
    compliance_status VARCHAR(50) DEFAULT 'unknown',
    last_assessed_at TIMESTAMPTZ,
    next_assessment_due DATE,
    
    notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_compliance_tenant ON compliance_rules(tenant_id);
CREATE INDEX idx_compliance_regulation ON compliance_rules(tenant_id, regulation_name);
CREATE INDEX idx_compliance_status ON compliance_rules(tenant_id, compliance_status);

-- Audit logs — complete activity trail
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id UUID,
    
    details JSONB NOT NULL DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_action ON audit_logs(tenant_id, action);
CREATE INDEX idx_audit_created ON audit_logs(tenant_id, created_at DESC);

-- ============================================
-- ROW-LEVEL SECURITY (RLS) POLICIES
-- Enforces tenant isolation at the database level
-- ============================================

-- Enable RLS on all tenant-scoped tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Create RLS policies — uses a session variable 'app.current_tenant_id'
-- The application sets this via: SET app.current_tenant_id = '<tenant-uuid>';

CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_documents ON documents
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_entities ON entities
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_embeddings ON document_embeddings
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_conversations ON conversations
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_messages ON messages
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_maintenance ON maintenance_records
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_compliance ON compliance_rules
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation_audit ON audit_logs
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- ============================================
-- SEED DATA — Sample tenant for development
-- ============================================
INSERT INTO tenants (id, name, slug, subscription_tier, max_documents, max_users)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'Demo Refinery Corp',
    'demo-refinery',
    'professional',
    100000,
    100
);

-- Default admin user (password: veda_admin_2024)
INSERT INTO users (id, tenant_id, email, name, role, password_hash)
VALUES (
    'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22',
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'admin@demo-refinery.com',
    'Admin User',
    'admin',
    '$2b$12$placeholder_hash_replace_with_real'
);

-- Structured previews of Word, Excel and PowerPoint uploads for the upload page
CREATE TABLE IF NOT EXISTS document_previews (
    document_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    preview JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
