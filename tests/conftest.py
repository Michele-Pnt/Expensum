import os
import sys
import pytest
from unittest.mock import MagicMock

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


def pytest_addoption(parser):
    """
    Aggiunge una opzione alla riga di comando di pytest:
    --real-ai: Se presente, i test utilizzeranno le API vere di Gemini/Ollama.
    """
    parser.addoption(
        "--real-ai",
        action="store_true",
        default=False,
        help="Esegue i test chiamando veramente le API delle AI (Gemini/Ollama)"
    )


@pytest.fixture(scope="session")
def use_real_ai(request):
    return request.config.getoption("--real-ai")


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
    flask_app.config.update({"TESTING": True})
    yield flask_app

@pytest.fixture
def client(app):
    """Client fittizio per simulare chiamate GET/POST alle route di Flask."""
    return app.test_client()
