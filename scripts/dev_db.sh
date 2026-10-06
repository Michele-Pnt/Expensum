#!/usr/bin/env bash
# =============================================================================
# dev_db.sh — gestione del database PostgreSQL locale per sviluppo e test.
# Documentazione: docs/development.md
#
# Comandi:
#   up        Avvia il container Postgres (localhost:5433)
#   down      Ferma il container (i dati restano nel volume)
#   reset     Distrugge il volume e reinizializza ruoli/RLS da zero
#   migrate   Applica le migration Alembic come ruolo OWNER (MIGRATION_DATABASE_URL)
#   psql      Apri psql come OWNER `expensum` (bypassa RLS: vedi tutto)
#   psql-app  Apri psql come ruolo runtime `expensum_app` (soggetto a RLS)
#   status    Stato del container e healthcheck
#   logs      Tail dei log di Postgres
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT_DIR/docker/compose.dev.yml")
CONTAINER="expensum-postgres-dev"

_load_env() {
  if [[ -f "$ROOT_DIR/.env.local" ]]; then
    set -a; # shellcheck disable=SC1091
    source "$ROOT_DIR/.env.local"; set +a
  else
    echo "Errore: manca .env.local — migrazione annullata per evitare il fallback SQLite." >&2
    return 1
  fi
}

case "${1:-}" in
  up)
    "${COMPOSE[@]}" up -d
    echo "✅ Postgres su localhost:5433 (db=expensum, owner=expensum, app=expensum_app)"
    ;;
  down)    "${COMPOSE[@]}" down ;;
  reset)
    echo "🧨 Distruggo il volume dati e reinizializzo ruoli/RLS…"
    "${COMPOSE[@]}" down -v
    "${COMPOSE[@]}" up -d
    echo "✅ Ambiente reinizializzato. Ricorda: ./scripts/dev_db.sh migrate"
    ;;
  migrate)
    _load_env
    if [[ -z "${MIGRATION_DATABASE_URL:-}" ]]; then
      echo "Errore: MIGRATION_DATABASE_URL è obbligatoria per le migration PostgreSQL." >&2
      exit 1
    fi
    cd "$ROOT_DIR"
    echo "⏫ alembic upgrade head (ruolo OWNER)…"
    "$ROOT_DIR/.venv/bin/alembic" upgrade head
    ;;
  psql)     docker exec -it "$CONTAINER" psql -U expensum -d expensum ;;
  psql-app) docker exec -it "$CONTAINER" psql -U expensum_app -d expensum ;;
  status)   "${COMPOSE[@]}" ps ;;
  logs)     "${COMPOSE[@]}" logs -f postgres ;;
  *)
    grep -E '^#( |=)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
