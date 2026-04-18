-- Count total conversations
SELECT COUNT(*) AS total_conversations
FROM conversations;

-- Count conversations per user
-- SELECT user_id, COUNT(*) AS total_conversations
-- FROM conversations
-- GROUP BY user_id
-- ORDER BY total_conversations DESC;
