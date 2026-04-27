#!/bin/bash
# Avvia in parallelo: ngrok, bot Telegram e dashboard Flask (tutti nel .venv)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

# Verifica che il .venv esista
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Errore: .venv non trovato in $PROJECT_DIR"
    exit 1
fi

# Verifica che ngrok sia installato
if ! command -v ngrok &> /dev/null; then
    echo "Errore: ngrok non è installato o non è nel PATH"
    exit 1
fi

echo "Avvio ambiente di sviluppo Finance-Agents..."
echo "Project dir: $PROJECT_DIR"
echo ""

cleanup() {
    echo ""
    echo "Arresto processi..."
    kill "$PID_NGROK" "$PID_BOT" "$PID_DASHBOARD" 2>/dev/null
    wait "$PID_NGROK" "$PID_BOT" "$PID_DASHBOARD" 2>/dev/null
    echo "Tutti i processi terminati."
}
trap cleanup EXIT INT TERM

# ngrok
echo "[ngrok]     avvio su porta 3000 (Frontend MUI) → log: logs/ngrok.log"
ngrok http 3000 --log=stdout > "$LOG_DIR/ngrok.log" 2>&1 &
PID_NGROK=$!

# Aspetta che ngrok sia pronto e leggi l'URL pubblico via API locale
echo "[ngrok]     attendo URL pubblico..."
NGROK_URL=""
for i in $(seq 1 15); do
    sleep 1
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
        | grep -o '"public_url":"https://[^"]*"' \
        | head -1 \
        | cut -d'"' -f4)
    [ -n "$NGROK_URL" ] && break
done

if [ -z "$NGROK_URL" ]; then
    echo "[ngrok]     ⚠ impossibile leggere l'URL — aggiorna .env manualmente"
else
    echo "[ngrok]     URL pubblico: $NGROK_URL"
    # Aggiorna WEBAPP_BASE_URL e NOTION_REDIRECT_URI nel .env
    ENV_FILE="$PROJECT_DIR/.env"
    sed -i "s|^WEBAPP_BASE_URL=.*|WEBAPP_BASE_URL=$NGROK_URL|" "$ENV_FILE"
    sed -i "s|^NOTION_REDIRECT_URI=.*|NOTION_REDIRECT_URI=$NGROK_URL/auth/notion/callback|" "$ENV_FILE"
    echo "[ngrok]     ✓ .env aggiornato (WEBAPP_BASE_URL, NOTION_REDIRECT_URI)"
fi

# Bot Telegram
echo "[bot]       avvio bot.py → log: logs/bot.log"
cd "$PROJECT_DIR"
"$VENV_PYTHON" bot.py > "$LOG_DIR/bot.log" 2>&1 &
PID_BOT=$!

# Dashboard Flask
echo "[dashboard] avvio src/dashboard/app.py → log: logs/dashboard.log"
"$VENV_PYTHON" src/dashboard/app.py > "$LOG_DIR/dashboard.log" 2>&1 &
PID_DASHBOARD=$!

echo ""
echo "Processi avviati:"
echo "  ngrok     PID $PID_NGROK"
echo "  bot       PID $PID_BOT"
echo "  dashboard PID $PID_DASHBOARD"
echo ""
echo "Log in tempo reale (Ctrl+C per fermare tutto):"
echo "──────────────────────────────────────────────"

# Segui i tre log in parallelo con prefisso colorato
tail -f "$LOG_DIR/ngrok.log" | sed 's/^/\033[36m[ngrok]\033[0m /' &
tail -f "$LOG_DIR/bot.log" | sed 's/^/\033[32m[bot]\033[0m /' &
tail -f "$LOG_DIR/dashboard.log" | sed 's/^/\033[33m[dashboard]\033[0m /' &

wait "$PID_NGROK" "$PID_BOT" "$PID_DASHBOARD"
