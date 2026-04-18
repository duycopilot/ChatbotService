-- Get all conversations with message count, ordered by latest activity
SELECT
    c.id,
    c.user_id,
    c.title,
    c.created_at,
    c.updated_at,
    COUNT(m.id) AS message_count
FROM conversations c
LEFT JOIN messages m ON m.conversation_id = c.id
GROUP BY c.id
ORDER BY c.updated_at DESC;

-- Get conversations for a specific user
-- SELECT * FROM conversations
-- WHERE user_id = :user_id
-- ORDER BY updated_at DESC;

-- Get a single conversation by id
-- SELECT * FROM conversations
-- WHERE id = :conversation_id;
