"""Client Vertex AI condiviso per la trascrizione vocale (bot Telegram e webapp)."""
import json

from google import genai
from google.oauth2 import service_account

from config import Config


def get_vertex_ai_client() -> genai.Client:
    """Crea un client Vertex AI (regione EU, GDPR compliant).

    Se `GOOGLE_APPLICATION_CREDENTIALS_JSON` è valorizzata usa quella service account key
    esplicitamente (utile su ambienti come il VPS dove non è disponibile un file di
    Application Default Credentials). Altrimenti ricade sulle ADC standard di Google.
    """
    credentials = None
    if Config.GOOGLE_APPLICATION_CREDENTIALS_JSON:
        info = json.loads(Config.GOOGLE_APPLICATION_CREDENTIALS_JSON)
        credentials = service_account.Credentials.from_service_account_info(info)

    return genai.Client(
        vertexai=True,
        project=Config.GOOGLE_CLOUD_PROJECT,
        location=Config.VERTEX_AI_LOCATION,
        credentials=credentials,
    )
