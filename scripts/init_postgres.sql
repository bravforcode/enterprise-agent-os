-- Graxia Tool — PostgreSQL schema
-- This runs on first postgres container start

-- Cache table
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at DOUBLE PRECISION,
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

-- Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    user_id TEXT,
    resource TEXT,
    action TEXT,
    result TEXT,
    metadata JSONB,
    ip_address INET
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);

-- Cost tracking table
CREATE TABLE IF NOT EXISTS cost_records (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cost_usd NUMERIC(10, 6) NOT NULL,
    saved_usd NUMERIC(10, 6) DEFAULT 0,
    cache_hit BOOLEAN DEFAULT FALSE,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_cost_user ON cost_records(user_id);
CREATE INDEX IF NOT EXISTS idx_cost_model ON cost_records(model);
CREATE INDEX IF NOT EXISTS idx_cost_time ON cost_records(timestamp);

-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vault_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings JSONB
);
