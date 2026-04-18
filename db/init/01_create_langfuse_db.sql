-- Create the Langfuse database if it doesn't exist.
-- This script runs automatically on first postgres container start.
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
