-- Seed data for conversations, messages, and feedback tables
-- Requires pgcrypto extension (gen_random_uuid())

-- ============================================================
-- users
-- ============================================================
INSERT INTO users (id, full_name, email, phone_number, date_of_birth, gender, metadata) VALUES
    ('user_001', 'Nguyen Van A', 'user001@example.com', '0900000001', '1990-04-12', 'male', '{"preferred_language": "vi", "city": "Ho Chi Minh City"}'::jsonb),
    ('user_002', 'Tran Thi B', 'user002@example.com', '0900000002', '1988-09-03', 'female', '{"preferred_language": "en", "city": "Da Nang"}'::jsonb),
    ('user_003', 'Le Van C', 'user003@example.com', '0900000003', '1995-01-21', 'male', '{"preferred_language": "vi", "city": "Ha Noi"}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- conversations
-- ============================================================
INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES
    ('a1000000-0000-0000-0000-000000000001', 'user_001', 'Python basics help',          '2026-03-01 08:00:00', '2026-03-01 08:45:00'),
    ('a1000000-0000-0000-0000-000000000002', 'user_002', 'SQL query optimization',       '2026-03-02 09:00:00', '2026-03-02 09:30:00'),
    ('a1000000-0000-0000-0000-000000000003', 'user_001', 'Machine learning concepts',    '2026-03-03 10:00:00', '2026-03-03 11:00:00'),
    ('a1000000-0000-0000-0000-000000000004', 'user_003', 'REST API design patterns',     '2026-03-04 11:00:00', '2026-03-04 11:20:00'),
    ('a1000000-0000-0000-0000-000000000005', 'user_002', 'Docker and containerization',  '2026-03-05 14:00:00', '2026-03-05 14:50:00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- messages
-- ============================================================
INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) VALUES
    -- conversation 1: Python basics
    ('b1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001',
     'user',      'What is the difference between a list and a tuple in Python?',
     '{"tokens": 14}',
     '2026-03-01 08:00:00'),

    ('b1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000001',
     'assistant', 'A list is mutable (can be changed after creation) while a tuple is immutable. Lists use square brackets [] and tuples use parentheses (). Tuples are generally faster and can be used as dictionary keys.',
     '{"tokens": 43, "model": "gpt-4o", "latency_ms": 320}',
     '2026-03-01 08:00:30'),

    ('b1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000001',
     'user',      'Can you show me an example of each?',
     '{"tokens": 10}',
     '2026-03-01 08:01:00'),

    ('b1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000001',
     'assistant', 'Sure! List: my_list = [1, 2, 3]; my_list[0] = 10  # works fine. Tuple: my_tuple = (1, 2, 3); my_tuple[0] = 10  # raises TypeError.',
     '{"tokens": 52, "model": "gpt-4o", "latency_ms": 410}',
     '2026-03-01 08:01:40'),

    -- conversation 2: SQL
    ('b1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000002',
     'user',      'How do I speed up a slow SELECT query in PostgreSQL?',
     '{"tokens": 13}',
     '2026-03-02 09:00:00'),

    ('b1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000002',
     'assistant', 'Common approaches: 1) Add indexes on columns used in WHERE/JOIN clauses. 2) Use EXPLAIN ANALYZE to find bottlenecks. 3) Avoid SELECT *. 4) Use connection pooling. 5) Consider partitioning large tables.',
     '{"tokens": 55, "model": "gpt-4o", "latency_ms": 380}',
     '2026-03-02 09:00:45'),

    -- conversation 3: ML
    ('b1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000003',
     'user',      'What is overfitting in machine learning?',
     '{"tokens": 9}',
     '2026-03-03 10:00:00'),

    ('b1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000003',
     'assistant', 'Overfitting occurs when a model learns the training data too well, including its noise and outliers, resulting in poor generalization to new data. Common remedies: regularization, dropout, more training data, or early stopping.',
     '{"tokens": 58, "model": "gpt-4o", "latency_ms": 450}',
     '2026-03-03 10:01:00'),

    -- conversation 4: REST API
    ('b1000000-0000-0000-0000-000000000009', 'a1000000-0000-0000-0000-000000000004',
     'user',      'Should I use PUT or PATCH for partial updates?',
     '{"tokens": 11}',
     '2026-03-04 11:00:00'),

    ('b1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000004',
     'assistant', 'Use PATCH for partial updates (only the fields provided are changed) and PUT for full replacement of the resource. PATCH is more bandwidth-efficient when only a subset of fields needs updating.',
     '{"tokens": 47, "model": "gpt-4o", "latency_ms": 295}',
     '2026-03-04 11:00:35'),

    -- conversation 5: Docker
    ('b1000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000005',
     'user',      'What is the difference between a Docker image and a container?',
     '{"tokens": 15}',
     '2026-03-05 14:00:00'),

    ('b1000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000005',
     'assistant', 'A Docker image is a read-only template (blueprint) used to create containers. A container is a running instance of an image — it adds a writable layer on top and executes the defined process.',
     '{"tokens": 49, "model": "gpt-4o", "latency_ms": 310}',
     '2026-03-05 14:00:50')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- user_health_facts
-- ============================================================
INSERT INTO user_health_facts (
    id,
    user_id,
    conversation_id,
    source_message_id,
    entity_type,
    entity_key,
    attribute_key,
    value_text,
    value_json,
    canonical_value,
    unit,
    vector_id,
    category,
    clinical_status,
    verification_status,
    content,
    confidence,
    observed_at,
    is_active,
    metadata,
    created_at,
    updated_at,
    last_accessed_at
) VALUES
    (
        'd1000000-0000-0000-0000-000000000001',
        'user_001',
        'a1000000-0000-0000-0000-000000000001',
        'b1000000-0000-0000-0000-000000000001',
        'patient',
        'self',
        'communication_preference',
        'clear step-by-step explanations',
        NULL,
        'clear_step_by_step_explanations',
        NULL,
        'e1000000-0000-0000-0000-000000000001',
        'preference',
        'active',
        'self_reported',
        'Patient prefers clear step-by-step explanations.',
        0.91,
        '2026-03-01 08:00:00',
        TRUE,
        '{"source": "seed", "priority": "medium"}'::jsonb,
        '2026-03-01 08:02:00',
        '2026-03-01 08:02:00',
        '2026-03-05 09:00:00'
    ),
    (
        'd1000000-0000-0000-0000-000000000002',
        'user_001',
        'a1000000-0000-0000-0000-000000000003',
        'b1000000-0000-0000-0000-000000000007',
        'patient',
        'self',
        'care_goal',
        'understand core machine learning concepts',
        NULL,
        'understand_core_machine_learning_concepts',
        NULL,
        'e1000000-0000-0000-0000-000000000002',
        'goal',
        'active',
        'self_reported',
        'Patient wants to understand core machine learning concepts.',
        0.86,
        '2026-03-03 10:00:00',
        TRUE,
        '{"source": "seed", "topic": "education"}'::jsonb,
        '2026-03-03 10:02:00',
        '2026-03-03 10:02:00',
        '2026-03-05 09:05:00'
    ),
    (
        'd1000000-0000-0000-0000-000000000003',
        'user_002',
        'a1000000-0000-0000-0000-000000000002',
        'b1000000-0000-0000-0000-000000000005',
        'patient',
        'self',
        'chronic_condition',
        'hypertension',
        NULL,
        'hypertension',
        NULL,
        'e1000000-0000-0000-0000-000000000003',
        'condition',
        'active',
        'self_reported',
        'Patient has hypertension.',
        0.94,
        '2026-03-02 09:00:00',
        TRUE,
        '{"source": "seed", "risk_level": "high"}'::jsonb,
        '2026-03-02 09:01:00',
        '2026-03-02 09:01:00',
        '2026-03-05 09:10:00'
    ),
    (
        'd1000000-0000-0000-0000-000000000004',
        'user_002',
        'a1000000-0000-0000-0000-000000000002',
        'b1000000-0000-0000-0000-000000000005',
        'patient',
        'self',
        'blood_pressure',
        NULL,
        '{"systolic": 145, "diastolic": 92}'::jsonb,
        '{"diastolic":92,"systolic":145}',
        'mmHg',
        'e1000000-0000-0000-0000-000000000004',
        'vital_sign',
        'reported',
        'self_reported',
        'Patient blood pressure was 145/92 mmHg.',
        0.93,
        '2026-03-02 08:55:00',
        TRUE,
        '{"source": "seed", "measurement_context": "home"}'::jsonb,
        '2026-03-02 09:01:00',
        '2026-03-02 09:01:00',
        '2026-03-05 09:12:00'
    ),
    (
        'd1000000-0000-0000-0000-000000000005',
        'user_003',
        'a1000000-0000-0000-0000-000000000004',
        'b1000000-0000-0000-0000-000000000009',
        'patient', 
        'self',
        'allergy',
        'penicillin',
        NULL,
        'penicillin',
        NULL,
        'e1000000-0000-0000-0000-000000000005',
        'allergy',
        'active',
        'self_reported',
        'Patient is allergic to penicillin.',
        0.97,
        '2026-03-04 10:59:00',
        TRUE,
        '{"source": "seed", "severity": "moderate"}'::jsonb,
        '2026-03-04 11:01:00',
        '2026-03-04 11:01:00',
        '2026-03-05 09:15:00'
    ),
    (
        'd1000000-0000-0000-0000-000000000006',
        'user_003',
        'a1000000-0000-0000-0000-000000000004',
        'b1000000-0000-0000-0000-000000000009',
        'patient',
        'self',
        'medication_name',
        'lisinopril 10mg daily',
        NULL,
        'lisinopril_10mg_daily',
        NULL,
        'e1000000-0000-0000-0000-000000000006',
        'medication',
        'active',
        'self_reported',
        'Patient takes lisinopril 10mg daily.',
        0.90,
        '2026-03-04 10:59:00',
        TRUE,
        '{"source": "seed", "adherence": "reported"}'::jsonb,
        '2026-03-04 11:01:00',
        '2026-03-04 11:01:00',
        '2026-03-05 09:16:00'
    )
ON CONFLICT (user_id, entity_type, entity_key, attribute_key, canonical_value) DO NOTHING;

-- ============================================================
-- feedback
-- ============================================================
INSERT INTO feedback (id, message_id, is_liked, comment, created_at) VALUES
    ('c1000000-0000-0000-0000-000000000001', 'b1000000-0000-0000-0000-000000000002',
     TRUE,  'Very clear explanation, thanks!',               '2026-03-01 08:02:00'),

    ('c1000000-0000-0000-0000-000000000002', 'b1000000-0000-0000-0000-000000000004',
     TRUE,  'The code example helped a lot.',                '2026-03-01 08:03:00'),

    ('c1000000-0000-0000-0000-000000000003', 'b1000000-0000-0000-0000-000000000006',
     TRUE,  NULL,                                            '2026-03-02 09:02:00'),

    ('c1000000-0000-0000-0000-000000000004', 'b1000000-0000-0000-0000-000000000008',
     FALSE, 'Could use a more concrete code example.',       '2026-03-03 10:05:00'),

    ('c1000000-0000-0000-0000-000000000005', 'b1000000-0000-0000-0000-000000000010',
     TRUE,  'Exactly what I needed.',                        '2026-03-04 11:02:00'),

    ('c1000000-0000-0000-0000-000000000006', 'b1000000-0000-0000-0000-000000000012',
     TRUE,  'Great analogy with blueprint and instance.',    '2026-03-05 14:02:00')
ON CONFLICT (id) DO NOTHING;
