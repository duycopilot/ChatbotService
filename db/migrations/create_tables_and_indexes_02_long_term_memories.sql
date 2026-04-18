CREATE TABLE user_health_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    entity_type VARCHAR(50) NOT NULL DEFAULT 'patient',
    entity_key TEXT NOT NULL DEFAULT 'self',
    attribute_key VARCHAR(100) NOT NULL,
    value_text TEXT,
    value_json JSONB,
    canonical_value TEXT NOT NULL,
    unit VARCHAR(50),
    vector_id UUID NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL DEFAULT 'general',
    clinical_status VARCHAR(30),
    verification_status VARCHAR(30) NOT NULL DEFAULT 'self_reported',
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    observed_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP
);

CREATE UNIQUE INDEX uq_user_health_facts_fact_identity
ON user_health_facts(user_id, entity_type, entity_key, attribute_key, canonical_value);

CREATE INDEX idx_user_health_facts_user_id
ON user_health_facts(user_id);

CREATE INDEX idx_user_health_facts_user_attribute
ON user_health_facts(user_id, attribute_key);

CREATE INDEX idx_user_health_facts_user_active
ON user_health_facts(user_id, is_active);

CREATE INDEX idx_user_health_facts_conversation_id
ON user_health_facts(conversation_id);