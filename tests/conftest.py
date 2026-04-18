import os
import pytest
from unittest.mock import MagicMock

# Forza l'ambiente in modalità di testing PRIMA che qualsiasi altra cosa venga importata
os.environ["TESTING"] = "True"

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

# Variabili ambientali di TEST (Mock)
os.environ["TELEGRAM_BOT_TOKEN"] = "test_telegram_token"
os.environ["NOTION_OAUTH_CLIENT_ID"] = "test_client_id"
os.environ["NOTION_OAUTH_CLIENT_SECRET"] = "test_client_secret"

# Rende disponibili i path di src globalmente
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.user_store import UserStore, Base
from src.dashboard.app import app as flask_app

@pytest.fixture
def mock_db_session():
    """Restituisce un database SQLite in memoria, isolato e azzerato per ogni test."""
    # Usiamo il costruttore di UserStore ma con un URL sqlite in RAM
    store = UserStore(db_url="sqlite:///:memory:")
    # Drop e Create (anche se memory parte vuoto, per sicurezza)
    Base.metadata.drop_all(store.engine)
    Base.metadata.create_all(store.engine)
    
    yield store
    
    # Clean up dopo il test
    store.engine.dispose()

@pytest.fixture
def app():
    """Fixture necessaria per pytest-flask."""
    flask_app.config.update({
        "TESTING": True,
    })
    yield flask_app

@pytest.fixture
def client(app):
    """Client fittizio per simulare chiamate GET/POST alle route di Flask."""
    return app.test_client()
