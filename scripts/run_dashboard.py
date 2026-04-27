#!/usr/bin/env python3
"""
run_dashboard.py — Avvio della Web Dashboard per l'Amministratore (Fase 6).
Si appoggia a Flask e serve l'interfaccia UI.
"""
import logging
import sys
import os
from pathlib import Path

# Aggiunge la root del progetto al sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.dashboard.app import app

# Silenziamo log eccessivi di werkzeug
logging.getLogger('werkzeug').setLevel(logging.WARNING)

if __name__ == "__main__":
    print("🚀 Avvio della Dashboard Admin di Moneo su http://127.0.0.1:5000 ...")
    print("Premi CTRL+C per fermarla.")
    # In produzione si consiglia di usare gunicorn o waitress
    app.run(host="127.0.0.1", port=5000, debug=False)
