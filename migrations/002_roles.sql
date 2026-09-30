-- 002: application roles (passwords set by migrate.py from .env; idempotent)
DO $$ BEGIN CREATE ROLE hm_reader  NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE hm_analyst NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE hm_approver NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE hm_evaluator NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE hm_admin   NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
