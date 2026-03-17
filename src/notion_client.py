"""
src/notion_client.py — Estrazione dati dal database Notion delle spese.

Compatibile con notion-client v3 + Notion API 2025-09-03.

Gestisce tre database:
  1. Expense — transazioni di spesa
  2. Categories — mappa categorieID → nome
  3. Monthly Balance — "Risparmio Netto" mensile certificato (formula)

Approccio per le categorie:
  - Pre-carica TUTTO il database Categories in una dict {page_id → name}
  - In questo modo risolve ogni categoria in O(1) senza chiamate extra per pagina

Approccio per il Monthly Balance:
  - Interroga il database Monthly Balance per ottenere il "Risparmio Netto"
    (dato certo al 100%, calcolato da Notion come formula incassi - spese)
"""

import logging
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Optional

from notion_client import Client
from notion_client.errors import APIResponseError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import Config

logger = logging.getLogger("financial_agent.notion")


class NotionExpenseClient:
    """Client per l'estrazione dati da tutti i database Notion necessari."""

    def __init__(self):
        self._client = Client(auth=Config.NOTION_API_KEY)
        # Caches
        self._data_source_cache: dict[str, str] = {}   # db_id → data_source_id
        self._category_map: dict[str, dict] = {}       # page_id → {"name": str, "average": float}
        self._categories_loaded = False

    # ------------------------------------------------------------------
    # Risoluzione data_source_id (API 2025-09-03)
    # ------------------------------------------------------------------
    def _get_data_source_id(self, database_id: str) -> str:
        """Recupera e mette in cache il data_source_id per un dato database_id."""
        if database_id in self._data_source_cache:
            return self._data_source_cache[database_id]

        db = self._client.databases.retrieve(database_id=database_id)
        data_sources = db.get("data_sources", [])
        if not data_sources:
            # Fallback per eventuale API legacy
            self._data_source_cache[database_id] = database_id
            return database_id

        ds_id = data_sources[0]["id"]
        self._data_source_cache[database_id] = ds_id
        logger.info(f"DB {database_id[:8]}... → data_source_id {ds_id[:8]}...")
        return ds_id

    # ------------------------------------------------------------------
    # Pre-caricamento bulk delle categorie
    # ------------------------------------------------------------------
    def _load_categories(self) -> None:
        """
        Carica TUTTO il database Categories in una dict {page_id → nome}.
        Va in graceful degradation se il DB non è accessibile.
        """
        if self._categories_loaded:
            return

        db_id = Config.NOTION_CATEGORIES_DATABASE_ID
        if not db_id:
            logger.warning("NOTION_CATEGORIES_DATABASE_ID non configurato.")
            self._categories_loaded = True
            return

        try:
            ds_id = self._get_data_source_id(db_id)
            has_more = True
            cursor = None
            count = 0

            while has_more:
                resp = self._query_with_retry(ds_id, {}, cursor)
                for page in resp.get("results", []):
                    page_id = page["id"]
                    props = page.get("properties", {})
                    # Cerca il campo "title" (nome categoria) e "formula"/"number" (average)
                    name = "Sconosciuta"
                    average_val = 0.0
                    for prop_name, prop in props.items():
                        if prop.get("type") == "title":
                            rt = prop.get("title", [])
                            if rt:
                                name = rt[0].get("plain_text", "Sconosciuta")
                        elif prop_name.lower() == "average":
                            ptype = prop.get("type", "")
                            if ptype == "formula":
                                f_val = prop.get("formula", {})
                                ftype = f_val.get("type", "")
                                if ftype == "number":
                                    average_val = float(f_val.get("number") or 0.0)
                            elif ptype == "number":
                                average_val = float(prop.get("number") or 0.0)
                                
                    self._category_map[page_id] = {"name": name, "average": average_val}
                    count += 1

                has_more = resp.get("has_more", False)
                cursor = resp.get("next_cursor")

            logger.info(f"Categorie caricate: {count} entries")
        except Exception as e:
            logger.warning(
                f"Impossibile caricare il database Categories: {e}\n"
                "Assicurati di aver condiviso l'integrazione con il database Categories."
            )
        finally:
            self._categories_loaded = True

    def _resolve_category(self, page_id: str) -> dict:
        """Risolve un page_id in nome e media categoria usando la mappa pre-caricata."""
        return self._category_map.get(page_id, {"name": "Sconosciuta", "average": 0.0})

    # ------------------------------------------------------------------
    # Parsing spese
    # ------------------------------------------------------------------
    def _parse_expense_page(self, page: dict) -> Optional[dict]:
        """
        Converte una pagina Notion del database Expense in
        {date, category, name, amount}.
        """
        props = page.get("properties", {})

        # --- DATA ---
        date_prop = props.get(Config.NOTION_COL_DATE, {})
        date_val = date_prop.get("date")
        if not date_val or not date_val.get("start"):
            return None
        try:
            tx_date = datetime.fromisoformat(date_val["start"]).date()
        except (ValueError, TypeError):
            return None

        # --- IMPORTO ---
        amount_prop = props.get(Config.NOTION_COL_AMOUNT, {})
        amount_val = amount_prop.get("number")
        if amount_val is None:
            return None
        amount = abs(float(amount_val))  # sempre positivo

        # --- NOME ---
        name_prop = props.get(Config.NOTION_COL_NAME, {})
        ptype = name_prop.get("type", "")
        rich = name_prop.get(ptype, [])
        name = rich[0].get("plain_text", "—") if rich else "—"

        # --- CATEGORIA (Relation → mappa pre-caricata) ---
        cat_prop = props.get(Config.NOTION_COL_CATEGORY, {})
        cat_type = cat_prop.get("type", "")
        category_name = "Senza categoria"
        category_average = 0.0

        if cat_type == "relation":
            relations = cat_prop.get("relation", [])
            if relations:
                cat_page_id = relations[0].get("id", "")
                if cat_page_id:
                    cat_info = self._resolve_category(cat_page_id)
                    category_name = cat_info["name"]
                    category_average = cat_info["average"]
        elif cat_type in ("select", "multi_select"):
            sel = cat_prop.get("select") or (cat_prop.get("multi_select") or [{}])[0]
            category_name = sel.get("name", "Senza categoria") if sel else "Senza categoria"

        return {
            "date": tx_date, 
            "category": category_name, 
            "category_average": category_average,
            "name": name, 
            "amount": amount
        }

    # ------------------------------------------------------------------
    # Fetch spese
    # ------------------------------------------------------------------
    def fetch_all_transactions(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Recupera tutte le transazioni dal database Expense.

        Returns:
            Lista di dict {date, category, name, amount} ordinata per data.
        """
        logger.info(
            f"Estrazione Expense [{start_date or 'inizio'} → {end_date or 'oggi'}]"
        )

        # 1. Pre-carica categorie
        self._load_categories()

        # 2. Risolvi data_source_id
        ds_id = self._get_data_source_id(Config.NOTION_EXPENSE_DATABASE_ID)

        # 3. Query paginata
        filters = self._build_date_filter(start_date, end_date)
        all_results = []
        has_more = True
        cursor = None
        page_num = 0

        while has_more:
            page_num += 1
            resp = self._query_with_retry(ds_id, filters, cursor)
            results = resp.get("results", [])
            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")
            logger.info(f"Pagina {page_num}: {len(results)} record")

            for page in results:
                parsed = self._parse_expense_page(page)
                if parsed:
                    all_results.append(parsed)

        all_results.sort(key=lambda x: x["date"])
        logger.info(
            f"Spese estratte: {len(all_results)} transazioni, "
            f"{len(self._category_map)} categorie disponibili"
        )
        return all_results

    # ------------------------------------------------------------------
    # Fetch Monthly Balance
    # ------------------------------------------------------------------
    def fetch_monthly_balances(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Recupera i record dal database Monthly Balance.

        Returns:
            Lista di dict {year, month, net_savings} ordinata per data.
            net_savings = valore del campo "Risparmio Netto" (formula Notion),
            dato certo al 100% (incassi - spese).
        """
        db_id = Config.NOTION_MONTHLY_BALANCE_DATABASE_ID
        if not db_id:
            logger.warning("NOTION_MONTHLY_BALANCE_DATABASE_ID non configurato.")
            return []

        try:
            ds_id = self._get_data_source_id(db_id)
        except Exception as e:
            logger.warning(
                f"Impossibile accedere al database Monthly Balance: {e}\n"
                "Assicurati di aver condiviso l'integrazione con il database Monthly Balance."
            )
            return []

        logger.info("Estrazione Monthly Balance...")

        # Per ora fetcha tutto (il DB è piccolo: un record per mese)
        balances = []
        has_more = True
        cursor = None

        while has_more:
            try:
                resp = self._query_with_retry(ds_id, {}, cursor)
            except Exception as e:
                logger.warning(f"Errore query Monthly Balance: {e}")
                break

            for page in resp.get("results", []):
                parsed = self._parse_monthly_balance_page(page)
                if parsed:
                    balances.append(parsed)

            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")

        # Filtra per intervallo se specificato
        if start_date:
            balances = [
                b for b in balances
                if date(b["year"], b["month"], 1) >= start_date.replace(day=1)
            ]
        if end_date:
            balances = [
                b for b in balances
                if date(b["year"], b["month"], 1) <= end_date.replace(day=1)
            ]

        balances.sort(key=lambda x: (x["year"], x["month"]))
        logger.info(f"Monthly Balance: {len(balances)} record trovati")
        return balances

    def _parse_monthly_balance_page(self, page: dict) -> Optional[dict]:
        """
        Converte una pagina del database Monthly Balance in
        {year, month, net_savings, label}.
        """
        props = page.get("properties", {})

        # --- DATA ---
        date_prop = props.get(Config.NOTION_MB_DATE, {})
        date_val = date_prop.get("date")
        if not date_val or not date_val.get("start"):
            # Cerca altri tipi di campo data (formula, created_time)
            return None
        try:
            mb_date = datetime.fromisoformat(date_val["start"]).date()
        except (ValueError, TypeError):
            return None

        # --- RISPARMIO NETTO (formula) ---
        net_prop = props.get(Config.NOTION_MB_NET_SAVINGS, {})
        net_savings = None

        prop_type = net_prop.get("type", "")
        if prop_type == "formula":
            formula_val = net_prop.get("formula", {})
            ftype = formula_val.get("type", "")
            net_savings = formula_val.get(ftype)
        elif prop_type == "number":
            net_savings = net_prop.get("number")

        if net_savings is None:
            return None

        from calendar import month_name
        label = f"{month_name[mb_date.month]} {mb_date.year}"

        return {
            "year": mb_date.year,
            "month": mb_date.month,
            "net_savings": float(net_savings),
            "label": label,
        }

    # ------------------------------------------------------------------
    # Fetch Income
    # ------------------------------------------------------------------
    def fetch_income(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Recupera le entrate dal database Income.

        Returns:
            Lista di dict {date, name, amount} ordinata per data.
        """
        db_id = Config.NOTION_INCOME_DATABASE_ID
        if not db_id:
            logger.warning("NOTION_INCOME_DATABASE_ID non configurato.")
            return []

        try:
            ds_id = self._get_data_source_id(db_id)
        except Exception as e:
            logger.warning(f"Impossibile accedere al database Income: {e}")
            return []

        logger.info(f"Estrazione Income [{start_date or 'inizio'} → {end_date or 'oggi'}]")
        
        filters = self._build_date_filter(start_date, end_date)
        incomes = []
        has_more = True
        cursor = None

        while has_more:
            try:
                resp = self._query_with_retry(ds_id, filters, cursor)
            except Exception as e:
                logger.warning(f"Errore query Income: {e}")
                break

            for page in resp.get("results", []):
                parsed = self._parse_income_page(page)
                if parsed:
                    incomes.append(parsed)

            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")

        incomes.sort(key=lambda x: x["date"])
        logger.info(f"Income: {len(incomes)} record trovati")
        return incomes

    def _parse_income_page(self, page: dict) -> Optional[dict]:
        props = page.get("properties", {})

        # --- DATA ---
        date_prop = props.get(Config.NOTION_COL_DATE, {})
        date_val = date_prop.get("date")
        if not date_val or not date_val.get("start"):
            return None
        try:
            tx_date = datetime.fromisoformat(date_val["start"]).date()
        except (ValueError, TypeError):
            return None

        # --- IMPORTO ---
        amount_prop = props.get(Config.NOTION_COL_AMOUNT, {})
        amount_val = amount_prop.get("number")
        if amount_val is None:
            return None
        amount = float(amount_val)

        # --- NOME ---
        name_prop = props.get(Config.NOTION_COL_NAME, {})
        ptype = name_prop.get("type", "")
        rich = name_prop.get(ptype, [])
        name = rich[0].get("plain_text", "—") if rich else "—"

        return {"date": tx_date, "name": name, "amount": amount}

    # ------------------------------------------------------------------
    # Fetch Accounts
    # ------------------------------------------------------------------
    def fetch_accounts(self) -> list[dict]:
        """
        Recupera il saldo corrente da tutti i conti nel database Accounts.

        Returns:
            Lista di dict {name, current_balance}.
        """
        db_id = Config.NOTION_ACCOUNTS_DATABASE_ID
        if not db_id:
            logger.warning("NOTION_ACCOUNTS_DATABASE_ID non configurato.")
            return []

        try:
            ds_id = self._get_data_source_id(db_id)
        except Exception as e:
            logger.warning(f"Impossibile accedere al database Accounts: {e}")
            return []

        logger.info("Estrazione bilanci Accounts...")
        accounts = []
        has_more = True
        cursor = None

        while has_more:
            try:
                resp = self._query_with_retry(ds_id, {}, cursor)
            except Exception as e:
                logger.warning(f"Errore query Accounts: {e}")
                break

            for page in resp.get("results", []):
                parsed = self._parse_account_page(page)
                if parsed:
                    accounts.append(parsed)

            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")

        logger.info(f"Accounts: {len(accounts)} conti trovati")
        return accounts

    def _parse_account_page(self, page: dict) -> Optional[dict]:
        props = page.get("properties", {})
        page_id = page.get("id", "")

        # --- NOME ---
        name_prop = props.get(Config.NOTION_ACCOUNTS_COL_NAME, {})
        ptype = name_prop.get("type", "")
        rich = name_prop.get(ptype, [])
        name = rich[0].get("plain_text", "Sconosciuto") if rich else "Sconosciuto"

        # --- SALDO CALCOLATO IN CODICE ---
        try:
            initial_amount = self._read_account_component(
                page_id,
                props,
                Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT,
            )
            total_income = self._read_account_component(
                page_id,
                props,
                Config.NOTION_ACCOUNTS_COL_TOTAL_INCOME,
            )
            total_transfer_in = self._read_account_component(
                page_id,
                props,
                Config.NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_IN,
            )
            total_expense = self._read_account_component(
                page_id,
                props,
                Config.NOTION_ACCOUNTS_COL_TOTAL_EXPENSE,
            )
            total_transfer_out = self._read_account_component(
                page_id,
                props,
                Config.NOTION_ACCOUNTS_COL_TOTAL_TRANSFER_OUT,
            )
        except ValueError as e:
            logger.error("Account '%s' ignorato — campo mancante: %s", name, e)
            return None

        current_balance = (
            initial_amount
            + total_income
            + total_transfer_in
            - total_expense
            - total_transfer_out
        )

        logger.info(
            "Account '%s': saldo calcolato = €%.2f (init=€%.2f, income=€%.2f, in=€%.2f, expense=€%.2f, out=€%.2f)",
            name,
            current_balance,
            initial_amount,
            total_income,
            total_transfer_in,
            total_expense,
            total_transfer_out,
        )

        return {"name": name, "current_balance": float(current_balance)}

    def _read_account_component(
        self,
        page_id: str,
        props: dict,
        field_name: str,
    ) -> float:
        """Legge un componente numerico del saldo account.

        Raises:
            ValueError: se il campo non è presente nelle properties della pagina.
        """
        prop = props.get(field_name)
        if not prop:
            raise ValueError(
                f"Campo '{field_name}' non trovato nelle properties dell'account. "
                "Verifica il nome del campo nella configurazione "
                "(es. NOTION_ACCOUNTS_COL_INITIAL_AMOUNT)."
            )

        prop_value = None
        if page_id and prop.get("id"):
            prop_value = self._retrieve_page_property_with_retry(
                page_id=page_id,
                property_id=prop["id"],
            )

        numeric = self._extract_numeric_from_notion_property(prop_value)
        if numeric is None:
            numeric = self._extract_numeric_from_notion_property(prop)

        return float(numeric) if numeric is not None else 0.0

    @staticmethod
    def _extract_numeric_from_notion_property(prop: Optional[dict]) -> Optional[float]:
        """Estrae un valore numerico da una property Notion (number o formula)."""
        if not prop:
            return None

        # Risposta property endpoint (rollup/relation) può essere object="list"
        if prop.get("object") == "list":
            property_item = prop.get("property_item", {})
            ptype = property_item.get("type", "")
            if ptype == "rollup":
                rollup_val = property_item.get("rollup", {})
                if rollup_val.get("type") == "number":
                    val = rollup_val.get("number")
                    return float(val) if isinstance(val, (int, float)) else None
            return None

        ptype = prop.get("type", "")

        if ptype == "number":
            val = prop.get("number")
            return float(val) if isinstance(val, (int, float)) else None

        if ptype == "rollup":
            rollup_val = prop.get("rollup", {})
            if rollup_val.get("type") == "number":
                val = rollup_val.get("number")
                return float(val) if isinstance(val, (int, float)) else None
            return None

        if ptype != "formula":
            return None

        formula_val = prop.get("formula", {})
        ftype = formula_val.get("type", "")

        if ftype == "number":
            val = formula_val.get("number")
            return float(val) if isinstance(val, (int, float)) else None

        # Supporta formule che restituiscono stringhe tipo "€1,200.00" o "1.200,00 €"
        if ftype == "string":
            raw = formula_val.get("string")
            if not isinstance(raw, str) or not raw.strip():
                return None

            cleaned = raw.strip().replace("€", "").replace(" ", "")

            # Caso EU: 1.200,50 -> 1200.50
            if "," in cleaned and "." in cleaned:
                if cleaned.rfind(",") > cleaned.rfind("."):
                    cleaned = cleaned.replace(".", "").replace(",", ".")
                else:
                    cleaned = cleaned.replace(",", "")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")

            match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
            if not match:
                return None

            try:
                return float(match.group(0))
            except ValueError:
                return None

        return None

    # ------------------------------------------------------------------
    # Utility comuni
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _query_with_retry(
        self,
        data_source_id: str,
        filters: dict,
        start_cursor: Optional[str],
    ) -> dict:
        """Query generica su un data_source con retry automatico."""
        kwargs: dict = {"data_source_id": data_source_id}
        if filters:
            kwargs["filter"] = filters
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        return self._client.data_sources.query(**kwargs)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _retrieve_page_property_with_retry(
        self,
        page_id: str,
        property_id: str,
    ) -> Optional[dict]:
        """Recupera una property specifica di una pagina Notion via property endpoint."""
        try:
            return self._client.pages.properties.retrieve(
                page_id=page_id,
                property_id=property_id,
            )
        except APIResponseError as e:
            logger.warning(
                "Impossibile recuperare property '%s' per pagina %s: %s",
                property_id,
                page_id[:8],
                e,
            )
            return None

    @staticmethod
    def _build_date_filter(
        start_date: Optional[date], end_date: Optional[date]
    ) -> dict:
        """Costruisce il filtro date per la query Notion (campo Date)."""
        if not start_date and not end_date:
            return {}

        col = Config.NOTION_COL_DATE
        conditions = []
        if start_date:
            conditions.append({
                "property": col,
                "date": {"on_or_after": start_date.isoformat()},
            })
        if end_date:
            conditions.append({
                "property": col,
                "date": {"on_or_before": end_date.isoformat()},
            })

        return conditions[0] if len(conditions) == 1 else {"and": conditions}

    # ------------------------------------------------------------------
    # Test connessione
    # ------------------------------------------------------------------
    def test_connection(self) -> str:
        """Verifica la connessione e lo stato di accesso a tutti i database."""
        lines = []
        databases = [
            ("Expense", Config.NOTION_EXPENSE_DATABASE_ID),
            ("Categories", Config.NOTION_CATEGORIES_DATABASE_ID),
            ("Monthly Balance", Config.NOTION_MONTHLY_BALANCE_DATABASE_ID),
            ("Income", Config.NOTION_INCOME_DATABASE_ID),
            ("Accounts", Config.NOTION_ACCOUNTS_DATABASE_ID),
            ("Subscriptions", Config.NOTION_SUBSCRIPTIONS_DATABASE_ID),
            ("Pay/Transfer", Config.NOTION_PAY_TRANSFER_DATABASE_ID),
        ]
        for label, db_id in databases:
            if not db_id:
                lines.append(f"⚠️  {label}: ID non configurato nel .env")
                continue
            try:
                db = self._client.databases.retrieve(database_id=db_id)
                title = db.get("title", [{}])[0].get("plain_text", "?")
                lines.append(f"✅ {label}: '{title}'")
            except Exception as e:
                lines.append(f"❌ {label}: {str(e)[:80]}")
        return "\n".join(lines)
