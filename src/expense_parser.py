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
import time
import random
from datetime import date, datetime
import difflib

from config import Config

logger = logging.getLogger("financial_agent.expense_parser")

_SYSTEM_PROMPT = """Sei un assistente finanziario. Il tuo compito è estrarre informazioni finanziarie da messaggi scritti in modo informale in italiano. Devi capire dal contesto se si tratta di un'uscita (spesa) o di un'entrata (stipendio, regalo, rimborso, bonifico ricevuto).

REGOLE TASSATIVE:
1. Rispondi SOLO con un oggetto JSON valido, senza altro testo.
2. Il JSON deve avere esattamente questi 5 campi:
   - "type": stringa. Deve essere ASSOLUTAMENTE "expense" (se è una spesa/uscita) oppure "income" (se è un introito/entrata).
   - "amount": numero (float). DEVI interpretare anche i numeri a parole. Esempi: "150 mila euro" -> 150000.0, "cento euro" -> 100.0, "15" -> 15.0. Se non specificato, metti null.
   - "category": stringa. RIGOROSAMENTE UNA SOLA voce dalla lista fornita di Categorie. Se `type` è "income", metti "Introito" o null, a meno che non ci sia una categoria palese.
   - "name": stringa, breve descrizione (es. "Pizza amici", "Stipendio", "Busta Nonna"). Max 3 parole.
   - "date": stringa in formato "YYYY-MM-DD". Se non specificata, usa la data di oggi fornita.
3. Se il messaggio NON sembra una transazione finanziaria, rispondi con: {"error": "not_expense"}
4. NON inventare importi.

ESEMPI SPESE:
- "ieri pizza 25€" → {"type": "expense", "amount": 25.0, "category": "Ristoranti", "name": "Pizza", "date": "2026-03-20"}
- "netflix" → {"type": "expense", "amount": null, "category": "Abbonamenti", "name": "Netflix", "date": "2026-03-21"}
- "ho speso 67 euro al supermercato" → {"type": "expense", "amount": 67.0, "category": "Supermercato", "name": "Spesa supermercato", "date": "2026-03-21"}

ESEMPI ENTRATE:
- "ho ricevuto lo stipendio 1500" → {"type": "income", "amount": 1500.0, "category": null, "name": "Stipendio", "date": "2026-03-22"}
- "busta paga marzo 1800 euro" → {"type": "income", "amount": 1800.0, "category": null, "name": "Busta paga marzo", "date": "2026-03-22"}
- "rimborso spese 120€" → {"type": "income", "amount": 120.0, "category": null, "name": "Rimborso spese", "date": "2026-03-22"}
- "mi hanno pagato 500" → {"type": "income", "amount": 500.0, "category": null, "name": "Pagamento ricevuto", "date": "2026-03-22"}
- "bonifico ricevuto 300 euro" → {"type": "income", "amount": 300.0, "category": null, "name": "Bonifico ricevuto", "date": "2026-03-22"}
- "regalo compleanno 50 euro" → {"type": "income", "amount": 50.0, "category": null, "name": "Regalo compleanno", "date": "2026-03-22"}
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
        """Chiama Gemini con exponential backoff + jitter e fallback model."""
        from google.genai import types

        max_retries = 3
        base_delay = 1.0  # secondi
        models_to_try = [Config.GEMINI_MODEL, Config.GEMINI_FALLBACK_1, Config.GEMINI_FALLBACK_2]

        for model_name in models_to_try:
            for attempt in range(max_retries):
                try:
                    response = self._gemini_client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=_SYSTEM_PROMPT,
                            temperature=0.1,
                            max_output_tokens=1024,
                            response_mime_type="application/json",
                        ),
                    )
                    return response.text or ""
                except Exception as e:
                    error_str = str(e)
                    is_retryable = any(code in error_str for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))

                    if not is_retryable:
                        raise  # Errore non recuperabile, esci subito

                    if attempt < max_retries - 1:
                        # Exponential backoff con jitter
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"[Gemini] {model_name} tentativo {attempt + 1}/{max_retries} fallito "
                            f"({error_str[:80]}). Retry tra {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        is_last = (model_name == models_to_try[-1])
                        logger.warning(
                            f"[Gemini] {model_name} esaurito {max_retries} tentativi. "
                            f"{'Nessun altro fallback disponibile.' if is_last else 'Provo il prossimo modello di fallback...'}"
                        )

        # Se arriviamo qui, tutti i tentativi su tutti i modelli sono falliti
        raise RuntimeError("Tutti i modelli Gemini non disponibili dopo i retry.")

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
            # 1. Prova match esatto (case-insensitive)
            category_lower = category.lower()
            matched = next(
                (c for c in self._categories if c.lower() == category_lower),
                None,
            )
            
            # 2. Se non c'è match esatto, prova il fuzzy match
            if not matched:
                matches = difflib.get_close_matches(category_lower, [c.lower() for c in self._categories], n=1, cutoff=0.6)
                if matches:
                    # Recupera il nome originale con le maiuscole corrette
                    best_match_lower = matches[0]
                    matched = next(c for c in self._categories if c.lower() == best_match_lower)

            category = matched or category

        # Name
        _type = parsed.get("type", "expense")
        name = parsed.get("name") or ("Entrata" if _type == "income" else "Spesa")

        return {
            "type": parsed.get("type", "expense"), # per indentificare spesa o entrata 
            "date": expense_date,
            "amount": amount,
            "category": category,
            "name": name.strip(),
        }
