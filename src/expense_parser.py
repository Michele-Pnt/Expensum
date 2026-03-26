"""
src/expense_parser.py — Parser LLM per estrarre dati di spesa da testo libero.

L'utente scrive come a un amico:
  "ieri pizza con amici 25€"
  "ho speso 67 euro al supermercato"
  "netflix"

Il parser usa il LLM (Ollama o Gemini) per estrarre un JSON strutturato:
  {date, amount, category, name}
"""

import json
import logging
import re
from datetime import date, datetime

from config import Config

logger = logging.getLogger("financial_agent.expense_parser")

_SYSTEM_PROMPT = """Sei un assistente finanziario. Il tuo compito è estrarre informazioni di spesa da messaggi scritti in modo informale in italiano.

REGOLE TASSATIVE:
1. Rispondi SOLO con un oggetto JSON valido, senza altro testo.
2. Il JSON deve avere esattamente questi campi:
   - "amount": numero (float). DEVI interpretare anche i numeri a parole. Esempi: "150 mila euro" -> 150000.0, "cento euro" -> 100.0, "10k" -> 10000.0, "15" -> 15.0. Se non è specificato in alcun modo, metti null.
   - "category": stringa. Scegli RIGOROSAMENTE UNA SOLA voce dalla lista fornita di Categorie. Usa la deduzione (es. benzina -> Trasporti; Esselunga -> Spesa/Supermercato).
   - "name": stringa, breve descrizione spesa (es. "Pizza amici", "Esselunga", "Benzina"). Max 3 parole.
   - "date": stringa in formato "YYYY-MM-DD". Se non specificata, usa la data di oggi fornita.
3. Se il messaggio NON sembra una spesa o trasferimento, rispondi con: {"error": "not_expense"}
4. NON inventare importi.
5. Per la categoria, Scegli la più vicina o metti null.

ESEMPI:
- "ieri pizza 25€" → {"amount": 25.0, "category": "Ristoranti", "name": "Pizza", "date": "2026-03-20"}
- "ho comprato una lamborghini da 150mila euro" → {"amount": 150000.0, "category": "Auto", "name": "Lamborghini", "date": "2026-03-22"}
- "netflix" → {"amount": null, "category": "Abbonamenti", "name": "Netflix", "date": "2026-03-21"}
- "ciao come stai?" → {"error": "not_expense"}
"""


def _build_user_prompt(message: str, categories: list[str], today: date) -> str:
    """Costruisce il prompt utente con contesto."""
    cats_str = ", ".join(categories) if categories else "Nessuna categoria disponibile"
    return (
        f"Data di oggi: {today.isoformat()}\n"
        f"Categorie disponibili: [{cats_str}]\n\n"
        f"Messaggio dell'utente: \"{message}\""
    )


def _extract_json(text: str) -> dict | None:
    """Estrae un oggetto JSON dal testo, anche se circondato da altro testo."""
    # Prova prima il parsing diretto
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Cerca un blocco ```json ... ``` (o anche solo delimitato da backtick)
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Cerca un oggetto JSON nel testo
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


class ExpenseParser:
    """Parser LLM per estrarre dati di spesa da testo libero."""

    def __init__(self, categories: list[str] | None = None):
        """
        Args:
            categories: Lista nomi categorie da Notion (es. ["Affitto", "Supermercato", ...])
        """
        self._categories = categories or []

        if Config.LLM_PROVIDER == "ollama":
            import ollama as _ollama
            self._ollama_client = _ollama.Client(host=Config.OLLAMA_BASE_URL)
            self._provider = "ollama"
        else:
            from google import genai
            self._gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
            self._provider = "gemini"

        logger.info(
            f"ExpenseParser inizializzato con provider={self._provider}, "
            f"{len(self._categories)} categorie"
        )

    def parse(self, message: str) -> dict | None:
        """
        Parsa un messaggio di testo libero e restituisce i dati della spesa.

        Returns:
            dict con {date, amount, category, name} oppure None se non è una spesa.
            I campi possono essere null se non determinabili.
        """
        today = date.today()
        user_prompt = _build_user_prompt(message, self._categories, today)

        logger.info(f"Parsing messaggio: '{message[:50]}...' con {self._provider}")

        try:
            if self._provider == "ollama":
                raw_response = self._call_ollama(user_prompt)
            else:
                raw_response = self._call_gemini(user_prompt)
        except Exception as e:
            logger.error(f"Errore LLM durante il parsing: {e}")
            return None

        logger.debug(f"Risposta LLM grezza: {raw_response[:200]}")

        parsed = _extract_json(raw_response)
        if parsed is None:
            logger.warning(f"Impossibile estrarre JSON dalla risposta: {raw_response[:200]}")
            return None

        # Se il LLM dice che non è una spesa
        if "error" in parsed:
            logger.info(f"Messaggio non riconosciuto come spesa: {parsed.get('error')}")
            return None

        # Validazione e normalizzazione
        result = self._normalize(parsed, today)
        logger.info(f"Parsing completato: {result}")
        return result

    def _call_ollama(self, user_prompt: str) -> str:
        """Chiama Ollama per il parsing."""
        response = self._ollama_client.chat(
            model=Config.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.1, "num_predict": 256},
            format="json",
        )
        return response.message.content or ""

    def _call_gemini(self, user_prompt: str) -> str:
        """Chiama Gemini per il parsing."""
        from google.genai import types
        response = self._gemini_client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    def _normalize(self, parsed: dict, today: date) -> dict:
        """Normalizza e valida il risultato del parsing."""
        # Amount
        amount = parsed.get("amount")
        if amount is not None:
            try:
                amount = round(float(amount), 2)
            except (ValueError, TypeError):
                amount = None

        # Date
        date_str = parsed.get("date")
        try:
            expense_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today
        except (ValueError, TypeError):
            expense_date = today

        # Category — verifica che sia tra quelle disponibili
        category = parsed.get("category")
        if category and self._categories:
            # Fuzzy match: cerca la categoria più simile (case-insensitive)
            category_lower = category.lower()
            matched = next(
                (c for c in self._categories if c.lower() == category_lower),
                None,
            )
            if not matched:
                # Cerca per contenimento parziale
                matched = next(
                    (c for c in self._categories if category_lower in c.lower() or c.lower() in category_lower),
                    None,
                )
            category = matched or category  # usa il match o il valore originale

        # Name
        name = parsed.get("name") or "Spesa"

        return {
            "date": expense_date,
            "amount": amount,
            "category": category,
            "name": name.strip(),
        }
