CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新对话',
    status TEXT NOT NULL DEFAULT 'regular'
        CHECK (status IN ('regular', 'archived', 'deleted')),
    idempotency_key TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS conversations_user_idempotency_key_uq
    ON conversations (user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS conversations_user_updated_idx
    ON conversations (user_id, status, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    parent_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content JSONB NOT NULL,
    sequence BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'complete'
        CHECK (status IN ('pending', 'complete', 'failed', 'uncertain')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, sequence)
);

CREATE INDEX IF NOT EXISTS conversation_messages_page_idx
    ON conversation_messages (conversation_id, sequence DESC);

CREATE TABLE IF NOT EXISTS runtime_session_leases (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    runtime_session_id TEXT UNIQUE,
    status TEXT NOT NULL
        CHECK (status IN (
            'starting', 'active', 'degraded', 'expired',
            'stopping', 'stopped', 'stop_failed'
        )),
    source TEXT NOT NULL DEFAULT 'explicit'
        CHECK (source IN ('explicit', 'implicit')),
    owner_token UUID,
    started_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    start_latency_ms INTEGER,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS runtime_session_user_active_uq
    ON runtime_session_leases (user_id)
    WHERE status IN ('starting', 'active');

CREATE TABLE IF NOT EXISTS legacy_session_migrations (
    user_id TEXT NOT NULL,
    legacy_session_hash TEXT NOT NULL,
    conversation_id UUID REFERENCES conversations(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'complete', 'failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, legacy_session_hash)
);
