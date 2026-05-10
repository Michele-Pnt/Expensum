"""
src/expense_parser.py — Parser LLM per estrarre dati di spesa da testo libero.

L'utente scrive come a un amico:
    "ieri pizza con amici 25€"
    "ho speso 67 euro al supermercato"
    "netflix"

Il parser usa Mistral Small 3.1 per estrarre un JSON strutturato:
    {date, amount, category, name}
"""

import json
import logging
import re
import time
import random
from datetime import date, datetime
import difflib

from mistralai.client import Mistral

from config import Config

logger = logging.getLogger("financial_agent.expense_parser")

_INCOME_TYPES = [
    "Stipendio", "Bonus", "Rimborso", "Regalo", "Cashback",
    "Dividendi", "Affitto", "Interessi", "Mance", "Ripetizioni", "Paghetta",
]

_SYSTEM_PROMPT = """Sei un assistente finanziario. Il tuo compito è estrarre informazioni finanziarie da messaggi scritti in modo informale in italiano. Devi capire dal contesto se si tratta di un'uscita (spesa) o di un'entrata (stipendio, regalo, rimborso, bonifico ricevuto).

REGOLE TASSATIVE:
1. Rispondi SOLO con un oggetto JSON valido, senza altro testo.
2. Il JSON deve avere esattamente questi 6 campi:
   - "type": stringa. Deve essere ASSOLUTAMENTE "expense" (se è una spesa/uscita) oppure "income" (se è un introito/entrata).
   - "amount": numero (float). DEVI interpretare anche i numeri a parole. Esempi: "150 mila euro" -> 150000.0, "cento euro" -> 100.0, "15" -> 15.0. Se non specificato, metti null.
   - "category": stringa. RIGOROSAMENTE UNA SOLA voce dalla lista fornita di Categorie. Se `type` è "income", metti null.
   - "income_type": stringa. SOLO se `type` è "income": scegli OBBLIGATORIAMENTE una voce tra [Stipendio, Bonus, Rimborso, Regalo, Cashback, Dividendi, Affitto, Interessi, Mance, Ripetizioni, Paghetta]. Se `type` è "expense", metti null.
   - "name": stringa, breve descrizione (es. "Pizza amici", "Stipendio", "Busta Nonna"). Max 3 parole.
   - "date": stringa in formato "YYYY-MM-DD". Se non specificata, usa la data di oggi fornita.
3. Se il messaggio NON sembra una transazione finanziaria, rispondi con: {"error": "not_expense"}
4. NON inventare importi.

ESEMPI SPESE:
- "ieri pizza 25€" → {"type": "expense", "amount": 25.0, "category": "Ristoranti", "income_type": null, "name": "Pizza", "date": "2026-03-20"}
- "netflix" → {"type": "expense", "amount": null, "category": "Abbonamenti", "income_type": null, "name": "Netflix", "date": "2026-03-21"}
- "ho speso 67 euro al supermercato" → {"type": "expense", "amount": 67.0, "category": "Supermercato", "income_type": null, "name": "Spesa supermercato", "date": "2026-03-21"}

ESEMPI ENTRATE:
- "ho ricevuto lo stipendio 1500" → {"type": "income", "amount": 1500.0, "category": null, "income_type": "Stipendio", "name": "Stipendio", "date": "2026-03-22"}
- "busta paga marzo 1800 euro" → {"type": "income", "amount": 1800.0, "category": null, "income_type": "Stipendio", "name": "Busta paga marzo", "date": "2026-03-22"}
- "rimborso spese 120€" → {"type": "income", "amount": 120.0, "category": null, "income_type": "Rimborso", "name": "Rimborso spese", "date": "2026-03-22"}
- "mi hanno pagato 500" → {"type": "income", "amount": 500.0, "category": null, "income_type": "Stipendio", "name": "Pagamento ricevuto", "date": "2026-03-22"}
- "bonifico ricevuto 300 euro" → {"type": "income", "amount": 300.0, "category": null, "income_type": "Stipendio", "name": "Bonifico ricevuto", "date": "2026-03-22"}
- "regalo compleanno 50 euro" → {"type": "income", "amount": 50.0, "category": null, "income_type": "Regalo", "name": "Regalo compleanno", "date": "2026-03-22"}
- "cashback paypal 12 euro" → {"type": "income", "amount": 12.0, "category": null, "income_type": "Cashback", "name": "Cashback PayPal", "date": "2026-03-22"}
- "dividendi azionari 200 euro" → {"type": "income", "amount": 200.0, "category": null, "income_type": "Dividendi", "name": "Dividendi azionari", "date": "2026-03-22"}
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
        self._mistral_client = Mistral(api_key=Config.MISTRAL_API_KEY)

        logger.info(
            "ExpenseParser inizializzato con provider=mistral, "
            f"{len(self._categories)} categorie"
        )

    def parse(self, message: str) -> dict | None:
        """Parsa un messaggio e restituisce solo il risultato strutturato."""
        result, _usage = self.parse_with_usage(message)
        return result

    def parse_with_usage(self, message: str) -> tuple[dict | None, dict]:
        """
        Parsa un messaggio di testo libero e restituisce i dati della spesa.

        Returns:
            dict con {type, date, amount, category, name, income_type, usage_metadata} oppure None.
            `usage_metadata` contiene {prompt_tokens, completion_tokens, total_tokens,
            provider, model} per il ledger token reale.
        """
        today = date.today()
        user_prompt = _build_user_prompt(message, self._categories, today)

        logger.info(f"Parsing messaggio: '{message[:50]}...' con mistral")

        try:
            raw_response, usage = self._call_mistral(user_prompt)
        except Exception as e:
            logger.error(f"Errore LLM durante il parsing: {e}")
            return None, {}

        logger.debug(f"Risposta LLM grezza: {raw_response[:200]}")

        parsed = _extract_json(raw_response)
        if parsed is None:
            logger.warning(f"Impossibile estrarre JSON dalla risposta: {raw_response[:200]}")
            return None, usage

        # Se il LLM dice che non è una spesa
        if "error" in parsed:
            logger.info(f"Messaggio non riconosciuto come spesa: {parsed.get('error')}")
            return None, usage

        # Validazione e normalizzazione
        result = self._normalize(parsed, today)
        result["usage_metadata"] = usage
        logger.info(f"Parsing completato: {result}")
        return result, usage

    def _call_mistral(self, user_prompt: str) -> tuple[str, dict]:
        """Chiama Mistral con exponential backoff + jitter e fallback su Large.

        Returns:
            (content, usage_metadata) dove usage_metadata è:
            {prompt_tokens, completion_tokens, total_tokens, provider, model}
        """
        max_retries = 3
        base_delay = 1.0
        models_to_try = [Config.MISTRAL_SMALL_MODEL, Config.MISTRAL_LARGE_MODEL]

        for model_name in models_to_try:
            for attempt in range(max_retries):
                try:
                    response = self._mistral_client.chat.complete(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.1,
                        max_tokens=1024,
                        response_format={"type": "json_object"},
                    )
                    content = response.choices[0].message.content or ""
                    usage = {}
                    if response.usage:
                        prompt_tokens = response.usage.prompt_tokens or 0
                        completion_tokens = response.usage.completion_tokens or 0
                        total_tokens = response.usage.total_tokens or 0
                        if total_tokens <= 0:
                            total_tokens = prompt_tokens + completion_tokens
                        usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                            "provider": "mistral",
                            "model": model_name,
                        }
                    return content, usage
                except Exception as e:
                    error_str = str(e)
                    is_retryable = any(code in error_str for code in ("503", "429", "500", "rate limit", "too many"))

                    if not is_retryable:
                        raise

                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"[Mistral] {model_name} tentativo {attempt + 1}/{max_retries} fallito "
                            f"({error_str[:80]}). Retry tra {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        is_last = (model_name == models_to_try[-1])
                        logger.warning(
                            f"[Mistral] {model_name} esaurito {max_retries} tentativi. "
                            f"{'Nessun altro fallback disponibile.' if is_last else 'Provo con Mistral Large...'}"
                        )

        raise RuntimeError("Tutti i modelli Mistral non disponibili dopo i retry.")

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

        # Income type — valido solo per entrate, validato contro la lista ufficiale
        income_type: str | None = None
        if _type == "income":
            raw_income_type = parsed.get("income_type")
            if raw_income_type:
                raw_lower = raw_income_type.strip().lower()
                income_type = next(
                    (t for t in _INCOME_TYPES if t.lower() == raw_lower),
                    None,
                )
                if income_type is None:
                    # Fuzzy match come fallback
                    matches = difflib.get_close_matches(raw_lower, [t.lower() for t in _INCOME_TYPES], n=1, cutoff=0.6)
                    if matches:
                        income_type = next(t for t in _INCOME_TYPES if t.lower() == matches[0])

        return {
            "type": _type,  # per identificare spesa o entrata
            "date": expense_date,
            "amount": amount,
            "category": category,
            "income_type": income_type,
            "name": name.strip(),
        }
