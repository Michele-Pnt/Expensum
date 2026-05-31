import os
import sys
import pytest
from unittest.mock import MagicMock

# Stub preventivi per dipendenze grafiche pesanti: non vengono mai usate nei test
# (unit/integration), ma --cov=src le importerebbe tutte a collection time.
# setdefault garantisce che moduli già caricati (es. in IDE) non vengano sostituiti.
for _heavy in [
    "matplotlib", "matplotlib.pyplot", "matplotlib.figure",
    "matplotlib.axes", "matplotlib.patches",
    "seaborn",
]:
    sys.modules.setdefault(_heavy, MagicMock())

# Forza l'ambiente in modalità di testing PRIMA che qualsiasi altra cosa venga importata.
# DATABASE_URL punta a sqlite in memoria per evitare di toccare users.db reale durante i test.
os.environ["TESTING"] = "True"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TELEGRAM_BOT_TOKEN"] = "test_telegram_token"
os.environ["NOTION_OAUTH_CLIENT_ID"] = "test_client_id"
os.environ["NOTION_OAUTH_CLIENT_SECRET"] = "test_client_secret"

# Rende disponibili i path di src globalmente
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.user_store import UserStore, Base


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Svuota lo storage del rate limiter tra i test per evitare contaminazione incrociata."""
    try:
        from src.dashboard.app import limiter
        limiter.reset()
    except ImportError:
        pass
    yield


@pytest.fixture
def mock_db_session():
    """Restituisce un database SQLite in memoria, isolato e azzerato per ogni test."""
    store = UserStore(db_url="sqlite:///:memory:")
    Base.metadata.drop_all(store.engine)
    Base.metadata.create_all(store.engine)
    yield store
    store.engine.dispose()


@pytest.fixture
def app():
    """Fixture necessaria per pytest-flask. L'import avviene qui, non a livello di modulo,
    per evitare che la collection dei test apra una connessione al DB reale."""
    from src.dashboard.app import app as flask_app
    flask_app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield flask_app

@pytest.fixture
def client(app):
    """Client fittizio per simulare chiamate GET/POST alle route di Flask."""
    return app.test_client()
