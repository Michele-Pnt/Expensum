#!/bin/bash
# start_dev_postgres.sh — come start_dev.sh, ma agganciato al Postgres dockerizzato
# locale (.env.local) invece che al fallback sqlite silenzioso di config.py.
#
# config.py carica in automatico solo .env (mai .env.local) e DATABASE_URL ricade
# su sqlite:///users.db senza nessun errore se la variabile non è già nell'ambiente
# del processo. Questo script chiude quel buco: avvia Postgres, esporta .env.local
# nella propria shell PRIMA di lanciare bot/dashboard/frontend, così tutti i
# processi figli la ereditano.
#
# Uso:
#   ./scripts/start_dev_postgres.sh
#
# Se lo schema Postgres non è ancora stato applicato, esegui prima (una tantum):
#   ./scripts/dev_db.sh migrate

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

if [ ! -f "$PROJECT_DIR/.env.local" ]; then
    echo "Errore: manca .env.local — copialo da .env.local.example (vedi development documentation)" >&2
    exit 1
fi

echo "[postgres]  avvio/verifica container Docker..."
"$SCRIPT_DIR/dev_db.sh" up

echo "[postgres]  carico .env.local nell'ambiente di questa shell..."
set -a
# shellcheck disable=SC1091
source "$PROJECT_DIR/.env.local"
set +a
echo "[postgres]  DATABASE_URL attiva: $DATABASE_URL"

# Pulizia frontend residuo da esecuzioni precedenti (stesso motivo di start_dev.sh:
# terminale chiuso senza Ctrl+C lascia processi orfani).
pkill -f "next dev" 2>/dev/null || true
pkill -f "tail -f $LOG_DIR/frontend.log" 2>/dev/null || true

echo "[frontend]  avvio npm run dev → log: logs/frontend.log"
(cd "$PROJECT_DIR/frontend" && npm run dev) > "$LOG_DIR/frontend.log" 2>&1 &
PID_FRONTEND=$!

cleanup_frontend() {
    echo ""
    echo "[frontend]  arresto..."
    kill "$PID_FRONTEND" 2>/dev/null || true
    wait "$PID_FRONTEND" 2>/dev/null || true
    pkill -f "tail -f $LOG_DIR/frontend.log" 2>/dev/null || true
}
trap cleanup_frontend EXIT INT TERM

tail -f "$LOG_DIR/frontend.log" | sed 's/^/\033[35m[frontend]\033[0m /' &

# Rilancia lo start_dev.sh esistente (ngrok + bot + dashboard): eredita DATABASE_URL
# già esportata sopra, quindi bot.py/dashboard si agganciano a Postgres invece di
# ricadere silenziosamente su sqlite. Il trap/cleanup di start_dev.sh resta invariato
# per ngrok/bot/dashboard; quello qui sopra copre solo il frontend aggiunto da questo
# script.
"$SCRIPT_DIR/start_dev.sh"
