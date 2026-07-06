-- =============================================================================
-- Contract Intelligence Copilot — Database Initialisation
-- Runs automatically on first postgres container start
-- =============================================================================

-- Enable UUID generation (used for all primary keys)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For trigram text search on clause content

-- Create application role with least-privilege access
-- The application user should NOT have superuser privileges
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clm_app_role') THEN
        CREATE ROLE clm_app_role;
    END IF;
END
$$;
