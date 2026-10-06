-- =============================================================================
-- Ruolo applicativo runtime: expensum_app (DML-only, soggetto a RLS)
-- =============================================================================
-- Gira UNA SOLA VOLTA, al primo boot del container (volume dati vuoto), come
-- utente `expensum` sul database `expensum`. Riproduce 1:1 il ruolo runtime che
-- in produzione gira il bot/dashboard/scheduler via systemd.
--
-- Principio: l'app NON deve possedere le tabelle e NON deve poter fare DDL.
--   - NOSUPERUSER / NOBYPASSRLS → la Row-Level Security si applica davvero
--   - solo SELECT/INSERT/UPDATE/DELETE → una eventuale SQL injection non può
--     DROP/ALTER né leggere fuori dal proprio tenant (grazie alla RLS)
--
-- =============================================================================

CREATE ROLE expensum_app WITH
    LOGIN
    PASSWORD 'devapppassword'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOBYPASSRLS;

-- Accesso al database e allo schema, senza poter creare oggetti nello schema.
GRANT CONNECT ON DATABASE expensum TO expensum_app;
GRANT USAGE ON SCHEMA public TO expensum_app;
REVOKE CREATE ON SCHEMA public FROM expensum_app;

-- DML sulle tabelle/sequenze GIÀ esistenti. Al primo boot non ce ne sono ancora
-- (le crea Alembic dopo, come `expensum`), quindi questi grant coprono il caso in
-- cui si reinizializzi il volume dopo aver già applicato le migration.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO expensum_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO expensum_app;

-- DEFAULT PRIVILEGES: ogni tabella/sequenza creata IN FUTURO da `expensum` (cioè
-- da ogni nuova migration) viene automaticamente concessa in DML a `expensum_app`.
-- Senza questo, dopo ogni migration bisognerebbe ri-grantare a mano.
ALTER DEFAULT PRIVILEGES FOR ROLE expensum IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO expensum_app;
ALTER DEFAULT PRIVILEGES FOR ROLE expensum IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO expensum_app;
