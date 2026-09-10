"""Entry point WSGI della dashboard Flask.

Contratto esterno mantenuto per l'avvio (`scripts/run_dashboard.py` fa
`from src.dashboard.app import app`; gunicorn punta a `src.dashboard.app:app`):
questo file costruisce l'app via `create_app()` e registra tutti i blueprint
per area funzionale (vedi `src/dashboard/blueprints/` e `admin_routes.py`).
Non riesporta route, storage o helper per uso esterno.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.dashboard.factory import create_app  # noqa: E402
from src.dashboard.extensions import limiter  # noqa: E402  (re-export per tests/conftest.py)

from src.dashboard.admin_routes import admin_bp  # noqa: E402
from src.dashboard.blueprints.public import public_bp  # noqa: E402
from src.dashboard.blueprints.notifications_routes import notifications_bp  # noqa: E402
from src.dashboard.blueprints.goals_routes import goals_bp  # noqa: E402
from src.dashboard.blueprints.income_categories_routes import income_categories_bp  # noqa: E402
from src.dashboard.blueprints.space_routes import space_bp  # noqa: E402
from src.dashboard.blueprints.analytics_routes import analytics_bp  # noqa: E402
from src.dashboard.blueprints.reports_routes import reports_bp  # noqa: E402
from src.dashboard.blueprints.chat_routes import chat_bp  # noqa: E402
from src.dashboard.blueprints.privacy_routes import privacy_bp  # noqa: E402
from src.dashboard.blueprints.setup_routes import setup_bp  # noqa: E402
from src.dashboard.blueprints.auth_routes import auth_bp  # noqa: E402

app = create_app()

# Store condiviso già istanziato da create_app()/init_extensions() e registrato
# in app.config["STORE"]: ogni blueprint lo legge da lì (nessun import di
# app.py → nessun ciclo). Il bare name `store` resta qui solo come re-export
# per i test esistenti (tests/conftest.py e vari test_*.py fanno
# `from src.dashboard.app import store`): è lo stesso oggetto singleton, non
# una facciata.
store = app.config["STORE"]

app.register_blueprint(admin_bp)
app.register_blueprint(public_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(goals_bp)
app.register_blueprint(income_categories_bp)
app.register_blueprint(space_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(privacy_bp)
app.register_blueprint(setup_bp)
app.register_blueprint(auth_bp)


if __name__ == "__main__":
    # 5000 e' anche la porta di default di AirPlay Receiver su macOS (Control
    # Center), che intercetta le richieste locali con un 403 spurio: 5050
    # evita il conflitto senza dipendere da un'impostazione di sistema.
    app.run(host="127.0.0.1", port=5050, debug=False)
