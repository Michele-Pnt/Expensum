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

_SYSTEM_PROMPT = """Sei un assistente finanziario. Il tuo compito è estrarre informazioni finanziarie da messaggi scritti in modo informale in italiano. Devi capire dal contesto se si tratta di un'uscita (spesa), di un'entrata (stipendio, regalo, rimborso, bonifico ricevuto) o di uno spostamento di denaro tra due conti dello stesso utente (trasferimento/giroconto).

REGOLE TASSATIVE:
1. Rispondi SOLO con un oggetto JSON valido, senza altro testo.
2. Ogni transazione è un oggetto con esattamente questi 8 campi:
   - "type": stringa. Deve essere ASSOLUTAMENTE "expense" (se è una spesa/uscita), "income" (se è un introito/entrata) oppure "transfer" (se l'utente sposta soldi da un SUO conto a un ALTRO SUO conto — es. "sposta", "trasferisci", "giroconto", "bonifico interno").
   - "amount": numero (float). DEVI interpretare anche i numeri a parole. Esempi: "150 mila euro" -> 150000.0, "cento euro" -> 100.0, "15" -> 15.0. Se non specificato, metti null.
   - "category": stringa. RIGOROSAMENTE UNA SOLA voce dalla lista fornita di Categorie. Se `type` è "income" o "transfer", metti null.
   - "income_type": stringa. SOLO se `type` è "income": scegli OBBLIGATORIAMENTE una voce tra [Stipendio, Bonus, Rimborso, Regalo, Cashback, Dividendi, Affitto, Interessi, Mance, Ripetizioni, Paghetta]. Se `type` è "expense" o "transfer", metti null.
   - "name": stringa, breve descrizione (es. "Pizza amici", "Stipendio", "Busta Nonna", "Trasferimento"). Max 3 parole.
   - "date": stringa in formato "YYYY-MM-DD". Ragiona SEMPRE a partire dalla "Data di oggi" fornita nel prompt utente, che è il tuo unico ancoraggio temporale (non conosci la data reale). Interpreta QUALSIASI riferimento temporale relativo, a qualunque distanza: "ieri" (oggi-1), "ieri l'altro"/"altro ieri"/"avantieri" (oggi-2), "N giorni fa", "N settimane fa", "N mesi fa", nomi di giorni della settimana con "scorso" (es. "lunedì scorso" → il lunedì più recente nel passato, mai oggi stesso), "il mese scorso", date esplicite senza anno (es. "il 12 marzo" → stesso anno della data di oggi, o l'anno precedente se quel giorno è ancora futuro rispetto a oggi). Se non specificata alcuna data, usa la data di oggi fornita.
   - "from_account": stringa. SOLO se `type` è "transfer": il nome del conto di ORIGINE così come scritto/menzionato dall'utente (es. "conto corrente", "Revolut"). Se non menzionato o `type` non è "transfer", metti null. NON inventare un nome se l'utente non lo scrive.
   - "to_account": stringa. SOLO se `type` è "transfer": il nome del conto di DESTINAZIONE così come scritto/menzionato dall'utente. Se non menzionato o `type` non è "transfer", metti null. NON inventare un nome se l'utente non lo scrive.
3. Se il messaggio NON sembra una transazione finanziaria, rispondi con: {"error": "not_expense"}
4. NON inventare importi né nomi di conto.
5. MULTI-TRANSAZIONE — decidi tu se il messaggio ne descrive una sola o più di una:
   - Se il messaggio descrive UNA SOLA transazione, rispondi con l'oggetto singolo come negli esempi sotto (nessun wrapper).
   - Se il messaggio descrive PIÙ transazioni distinte (es. più importi/voci separati, anche con date diverse tra loro), rispondi con un oggetto wrapper: {"transactions": [ {oggetto transazione 1}, {oggetto transazione 2}, ... ]}, un elemento per ogni transazione rilevata, ciascuno con tutti e 8 i campi sopra. Ogni transazione può avere una propria "date" indipendente (tutte ancorate alla stessa "Data di oggi").
   - Non usare MAI il wrapper "transactions" per una singola transazione.

ESEMPI SPESE (transazione singola):
- "ieri pizza 25€" → {"type": "expense", "amount": 25.0, "category": "Ristoranti", "income_type": null, "name": "Pizza", "date": "2026-03-20", "from_account": null, "to_account": null}
- "netflix" → {"type": "expense", "amount": null, "category": "Abbonamenti", "income_type": null, "name": "Netflix", "date": "2026-03-21", "from_account": null, "to_account": null}
- "ho speso 67 euro al supermercato" → {"type": "expense", "amount": 67.0, "category": "Supermercato", "income_type": null, "name": "Spesa supermercato", "date": "2026-03-21", "from_account": null, "to_account": null}
- "3 settimane fa ho pagato 80 euro di dentista" (oggi=2026-04-10) → {"type": "expense", "amount": 80.0, "category": "Salute", "income_type": null, "name": "Dentista", "date": "2026-03-20", "from_account": null, "to_account": null}

ESEMPI ENTRATE (transazione singola):
- "ho ricevuto lo stipendio 1500" → {"type": "income", "amount": 1500.0, "category": null, "income_type": "Stipendio", "name": "Stipendio", "date": "2026-03-22", "from_account": null, "to_account": null}
- "busta paga marzo 1800 euro" → {"type": "income", "amount": 1800.0, "category": null, "income_type": "Stipendio", "name": "Busta paga marzo", "date": "2026-03-22", "from_account": null, "to_account": null}
- "rimborso spese 120€" → {"type": "income", "amount": 120.0, "category": null, "income_type": "Rimborso", "name": "Rimborso spese", "date": "2026-03-22", "from_account": null, "to_account": null}
- "mi hanno pagato 500" → {"type": "income", "amount": 500.0, "category": null, "income_type": "Stipendio", "name": "Pagamento ricevuto", "date": "2026-03-22", "from_account": null, "to_account": null}
- "bonifico ricevuto 300 euro" → {"type": "income", "amount": 300.0, "category": null, "income_type": "Stipendio", "name": "Bonifico ricevuto", "date": "2026-03-22", "from_account": null, "to_account": null}
- "regalo compleanno 50 euro" → {"type": "income", "amount": 50.0, "category": null, "income_type": "Regalo", "name": "Regalo compleanno", "date": "2026-03-22", "from_account": null, "to_account": null}
- "cashback paypal 12 euro" → {"type": "income", "amount": 12.0, "category": null, "income_type": "Cashback", "name": "Cashback PayPal", "date": "2026-03-22", "from_account": null, "to_account": null}
- "dividendi azionari 200 euro" → {"type": "income", "amount": 200.0, "category": null, "income_type": "Dividendi", "name": "Dividendi azionari", "date": "2026-03-22", "from_account": null, "to_account": null}

ESEMPI TRASFERIMENTI (transazione singola):
- "sposta 100 euro dal conto corrente al conto risparmio" → {"type": "transfer", "amount": 100.0, "category": null, "income_type": null, "name": "Trasferimento", "date": "2026-03-22", "from_account": "conto corrente", "to_account": "conto risparmio"}
- "giroconto di 50€ da Revolut a Fineco" → {"type": "transfer", "amount": 50.0, "category": null, "income_type": null, "name": "Giroconto", "date": "2026-03-22", "from_account": "Revolut", "to_account": "Fineco"}
- "bonifico interno 300 euro verso il conto risparmio" → {"type": "transfer", "amount": 300.0, "category": null, "income_type": null, "name": "Bonifico interno", "date": "2026-03-22", "from_account": null, "to_account": "conto risparmio"}
- "trasferisci 200 euro sul conto di risparmio" → {"type": "transfer", "amount": 200.0, "category": null, "income_type": null, "name": "Trasferimento", "date": "2026-03-22", "from_account": null, "to_account": "conto di risparmio"}

ESEMPI MULTI-TRANSAZIONE:
- "ho speso 10 euro per il pranzo, 20 di benzina e 5 di caffè ieri" (oggi=2026-04-10) → {"transactions": [
  {"type": "expense", "amount": 10.0, "category": "Ristoranti", "income_type": null, "name": "Pranzo", "date": "2026-04-09", "from_account": null, "to_account": null},
  {"type": "expense", "amount": 20.0, "category": "Trasporti", "income_type": null, "name": "Benzina", "date": "2026-04-09", "from_account": null, "to_account": null},
  {"type": "expense", "amount": 5.0, "category": "Bar", "income_type": null, "name": "Caffè", "date": "2026-04-09", "from_account": null, "to_account": null}
]}
- "oggi 15 euro di spesa e ieri ho ricevuto un rimborso di 50 euro" (oggi=2026-04-10) → {"transactions": [
  {"type": "expense", "amount": 15.0, "category": "Supermercato", "income_type": null, "name": "Spesa", "date": "2026-04-10", "from_account": null, "to_account": null},
  {"type": "income", "amount": 50.0, "category": null, "income_type": "Rimborso", "name": "Rimborso", "date": "2026-04-09", "from_account": null, "to_account": null}
]}
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

    def parse(self, message: str, chat_id: str = "unknown") -> dict | None:
        """Parsa un messaggio e restituisce solo il risultato strutturato."""
        result, _usage = self.parse_with_usage(message, chat_id)
        return result

    def parse_with_usage(self, message: str, chat_id: str = "unknown") -> tuple[dict | None, dict]:
        """
        Parsa un messaggio di testo libero e restituisce i dati della spesa.

        Returns:
            dict con {type, date, amount, category, name, income_type, from_account, to_account,
            usage_metadata} oppure None.
            `usage_metadata` contiene {prompt_tokens, completion_tokens, total_tokens,
            provider, model} per il ledger token reale.
        """
        today = date.today()
        user_prompt = _build_user_prompt(message, self._categories, today)

        logger.info(
            "parsing_expense",
            extra={"domain": "usage", "event": "parsing_expense", "chat_id": chat_id,
                   "meta": {"length": len(message)}},
        )

        try:
            raw_response, usage = self._call_mistral(user_prompt)
        except Exception as e:
            logger.error(
                "expense_parsing_llm_failed",
                extra={"domain": "usage", "event": "expense_parsing_llm_failed", "chat_id": chat_id,
                       "meta": {"error_type": type(e).__name__}},
            )
            return None, {}

        logger.debug(f"Risposta LLM grezza: {raw_response[:200]}")

        parsed = _extract_json(raw_response)
        if parsed is None:
            logger.warning(
                "json_extraction_failed",
                extra={"domain": "usage", "event": "json_extraction_failed", "chat_id": chat_id,
                       "meta": {"response_length": len(raw_response)}},
            )
            return None, usage

        # Se il LLM dice che non è una spesa
        if "error" in parsed:
            logger.info(
                "expense_not_recognized",
                extra={"domain": "usage", "event": "expense_not_recognized", "chat_id": chat_id,
                       "meta": {"reason": parsed.get("error")}},
            )
            return None, usage

        # Validazione e normalizzazione
        result = self._normalize(parsed, today)
        result["usage_metadata"] = usage
        logger.info(
            "parsing_expense_completed",
            extra={"domain": "usage", "event": "parsing_expense_completed", "chat_id": chat_id,
                   "meta": {"type": result.get("type")}},
        )
        return result, usage

    def parse_multi_with_usage(self, message: str, chat_id: str = "unknown") -> tuple[list[dict] | None, dict]:
        """
        Parsa un messaggio di testo libero e restituisce UNA O PIÙ transazioni.

        L'LLM decide autonomamente se il messaggio descrive una singola transazione
        (oggetto JSON semplice) o più transazioni distinte (wrapper {"transactions": [...]});
        qui normalizziamo sempre il risultato in una lista, con un elemento per transazione.

        Returns:
            (lista di dict con {type, date, amount, category, income_type, name, from_account, to_account}, usage_metadata)
            oppure (None, usage_metadata) se il messaggio non è riconosciuto come transazione
            finanziaria o il parsing fallisce.
        """
        today = date.today()
        user_prompt = _build_user_prompt(message, self._categories, today)

        logger.info(
            "parsing_expense_multi",
            extra={"domain": "usage", "event": "parsing_expense_multi", "chat_id": chat_id,
                   "meta": {"length": len(message)}},
        )

        try:
            raw_response, usage = self._call_mistral(user_prompt)
        except Exception as e:
            logger.error(
                "expense_parsing_multi_llm_failed",
                extra={"domain": "usage", "event": "expense_parsing_multi_llm_failed", "chat_id": chat_id,
                       "meta": {"error_type": type(e).__name__}},
            )
            return None, {}

        logger.debug(f"Risposta LLM grezza (multi): {raw_response[:200]}")

        parsed = _extract_json(raw_response)
        if parsed is None:
            logger.warning(
                "json_extraction_failed_multi",
                extra={"domain": "usage", "event": "json_extraction_failed_multi", "chat_id": chat_id,
                       "meta": {"response_length": len(raw_response)}},
            )
            return None, usage

        if "error" in parsed:
            logger.info(
                "expense_not_recognized",
                extra={"domain": "usage", "event": "expense_not_recognized", "chat_id": chat_id,
                       "meta": {"reason": parsed.get("error")}},
            )
            return None, usage

        raw_transactions = parsed["transactions"] if isinstance(parsed.get("transactions"), list) else [parsed]

        results = [self._normalize(item, today) for item in raw_transactions if isinstance(item, dict)]
        if not results:
            return None, usage

        logger.info(
            "parsing_expense_multi_completed",
            extra={"domain": "usage", "event": "parsing_expense_multi_completed", "chat_id": chat_id,
                   "meta": {"count": len(results)}},
        )
        return results, usage

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
        if not parsed.get("name"):
            default_names = {"income": "Entrata", "transfer": "Trasferimento"}
            name = default_names.get(_type, "Spesa")
        else:
            name = parsed["name"]

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

        # Conti di origine/destinazione — solo per trasferimenti. Sono nomi grezzi
        # così come scritti dall'utente: la risoluzione sui conti reali dell'utente
        # (match esatto/fuzzy) avviene a valle, in bot.py, dove sono disponibili
        # i conti effettivi (fetch_accounts) senza doverli passare all'LLM ad ogni messaggio.
        from_account: str | None = None
        to_account: str | None = None
        if _type == "transfer":
            raw_from = parsed.get("from_account")
            raw_to = parsed.get("to_account")
            from_account = raw_from.strip() if isinstance(raw_from, str) and raw_from.strip() else None
            to_account = raw_to.strip() if isinstance(raw_to, str) and raw_to.strip() else None

        return {
            "type": _type,  # per identificare spesa, entrata o trasferimento
            "date": expense_date,
            "amount": amount,
            "category": category,
            "income_type": income_type,
            "name": name.strip(),
            "from_account": from_account,
            "to_account": to_account,
        }
