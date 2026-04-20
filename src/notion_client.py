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


class NotionFinanceClient:
    """Client per l'estrazione dati da tutti i database Notion necessari."""

    @staticmethod
    def discover_databases(access_token: str, template_page_id: str | None = None) -> tuple[dict, list[str]]:
        """
        Discovery super-veloce basata su ricerca globale (Strategy: Trust search).
        Ritorna (discovered_map, all_candidates).
        """
        from notion_client import Client
        client = Client(auth=access_token)
        discovered = {}
        all_candidates = []
        
        # Mapping nomi -> chiavi interne (supportiamo singolari, plurali e sinonimi comuni)
        name_to_key = {
            "expense": "expense_db_id", "spese": "expense_db_id", "spesa": "expense_db_id", "uscita": "expense_db_id",
            "income": "income_db_id", "entrate": "income_db_id", "entrata": "income_db_id", "ricavo": "income_db_id",
            "categories": "categories_db_id", "categorie": "categories_db_id", "categoria": "categories_db_id",
            "monthly": "monthly_balance_db_id", "bilancio": "monthly_balance_db_id", "balance": "monthly_balance_db_id", "mensile": "monthly_balance_db_id",
            "accounts": "accounts_db_id", "conti": "accounts_db_id", "conto": "accounts_db_id",
            "subscriptions": "subscriptions_db_id", "abbonamenti": "subscriptions_db_id", "abbonamento": "subscriptions_db_id",
            "pay/transfer": "pay_transfer_db_id", "pay transfer": "pay_transfer_db_id", "transazione": "pay_transfer_db_id",
            "pay": "pay_transfer_db_id", "transfer": "pay_transfer_db_id", "trasferimento": "pay_transfer_db_id",
        }

        def _match_name(title_low: str) -> str | None:
            """Ritorna la chiave del DB se il titolo match con parole chiave."""
            # 1. Match Esatto con confini di parola (\b)
            for name, key in name_to_key.items():
                if "/" in name:
                    if name in title_low: return key
                    continue
                pattern = rf"\b{re.escape(name)}\b"
                if re.search(pattern, title_low):
                    return key
            
            # 2. Match Parziale (Substring) come fallback se non è stato trovato nulla
            # Utile per nomi composti come "Rimborso spesa"
            for name, key in name_to_key.items():
                if len(name) > 4 and name in title_low:
                     return key
            
            return None

        import time
        # Tipi di blocchi layout che possono contenere child_database/child_page
        # ma non hanno un campo "title" — vanno attraversati senza condizioni di nome.
        _LAYOUT_BLOCK_TYPES = {
            "column_list", "column", "toggle", "callout", "quote",
            "synced_block", "bulleted_list_item", "numbered_list_item",
        }

        def _fetch_db_title(db_id: str) -> str:
            """Recupera il titolo reale di un database via databases.retrieve().

            Serve quando il campo child_database.title del blocco è vuoto o
            "Untitled" (succede nelle pagine duplicate da template).
            """
            try:
                db = client.databases.retrieve(database_id=db_id)
                title_list = db.get("title", []) or []
                return "".join(t.get("plain_text", "") for t in title_list).strip()
            except Exception as e:
                logger.debug("[Discovery] databases.retrieve(%s) fallita: %s", db_id[:8], e)
                return ""

        def _fetch_page_title(page_id: str) -> str:
            """Recupera il titolo reale di una pagina via pages.retrieve().

            Serve quando il campo child_page.title del blocco è vuoto (stesso
            problema async di _fetch_db_title ma per le sub-pagine).
            """
            try:
                page = client.pages.retrieve(page_id=page_id)
                props = page.get("properties", {}) or {}
                for p in props.values():
                    if p.get("type") == "title":
                        return "".join(
                            t.get("plain_text", "") for t in p.get("title", [])
                        ).strip()
            except Exception as e:
                logger.debug("[Discovery] pages.retrieve(%s) fallita: %s", page_id[:8], e)
            return ""

        def _scan_recursive(block_id: str, depth: int = 0) -> None:
            """Scansiona blocchi ricorsivamente cercando child_database.

            Entra nei blocchi layout (column_list, column, toggle, ecc.) anche
            se non hanno un titolo, perché la pagina "Databases" del template
            è spesso annidatainside una colonna invece di essere figlia diretta.
            """
            if depth > 4: return
            try:
                # Rate limit protection (Notion doc: 3 req/s max)
                time.sleep(0.4)

                response = client.blocks.children.list(block_id=block_id)
                children = response.get("results", [])

                for block in children:
                    b_type = block.get("type", "")
                    b_id = block.get("id", "")

                    if b_type == "child_database":
                        title = block.get("child_database", {}).get("title", "") or ""
                        # Il campo child_database.title nei blocchi è spesso vuoto o "Untitled"
                        # quando il DB è in una pagina duplicata da template: bisogna recuperare
                        # il titolo reale con databases.retrieve().
                        if not title or title.strip().lower() in ("", "untitled"):
                            title = _fetch_db_title(b_id) or title
                        if title:
                            title_low = title.lower().strip()
                            logger.debug("[Discovery] Visto in '%s...': '%s' [child_database]", block_id[:5], title)
                            if title not in all_candidates:
                                all_candidates.append(title)
                            matched_key = _match_name(title_low)
                            if matched_key and matched_key not in discovered:
                                discovered[matched_key] = b_id
                                logger.info("[Discovery] MATCH TROVATO: %s -> %s", title, matched_key)

                    elif b_type == "child_page":
                        title = block.get("child_page", {}).get("title", "")
                        title_low = title.lower().strip() if title else ""
                        logger.debug("[Discovery] Visto in '%s...': '%s' [child_page]", block_id[:5], title)
                        # Entriamo se è una cartella nota o se siamo ai primi livelli
                        is_container = any(k in title_low for k in ["database", "db", "finance", "dashboard", "tracky"])
                        if is_container or depth < 2:
                            _scan_recursive(b_id, depth + 1)

                    elif b_type in _LAYOUT_BLOCK_TYPES and depth < 3:
                        # Layout block senza titolo: potrebbe contenere child_database annidati
                        _scan_recursive(b_id, depth + 1)

            except Exception as e:
                if "copy_indicator" not in str(e):
                    logger.warning("[Discovery] Blocco %s non leggibile: %s", block_id, e)

        # ---------------------------------------------------------------------------
        # Costanti del template
        # ---------------------------------------------------------------------------
        _ROOT_PAGE_NAME = "Dashboard Tracky Finance"
        _DATABASES_SUBPAGE_NAME = "databases"

        # Pagine di contenuto (leaf) del template: non entrarci durante la ricerca
        # di "Databases", altrimenti si scansionano centinaia di blocchi inutili.
        _LEAF_PAGE_TITLES = frozenset({
            "expenses", "expense", "accounts", "account", "income",
            "subscriptions", "subscription", "payment", "payments",
            "graphs", "graph", "budget", "report", "reports",
        })

        def _list_children(block_id: str) -> list:
            """Legge tutti i figli di un blocco con paginazione."""
            results: list = []
            cursor = None
            while True:
                kwargs: dict = {"block_id": block_id, "page_size": 100}
                if cursor:
                    kwargs["start_cursor"] = cursor
                resp = client.blocks.children.list(**kwargs)
                results.extend(resp.get("results", []))
                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")
            return results

        def _find_databases_subpage_id(start_id: str, depth: int = 0) -> str | None:
            """Trova la sub-page 'Databases' navigando ricorsivamente la struttura.

            Struttura reale del template:
              root → column_list → column → synced_block → Menu (child_page)
                   → Databases (child_page) → 7 child_database reali

            L'algoritmo entra in:
            - Tutti i blocchi layout (column_list, column, synced_block, callout…)
            - Le child_page intermedie NON-leaf (es. "Menu") fino a depth 5
            - NON entra nelle pagine di contenuto (Expenses, Accounts, Income…)
            """
            if depth > 7:
                return None
            try:
                children = _list_children(start_id)
            except Exception as e:
                logger.debug("[Discovery] Lettura blocco %s fallita: %s", start_id[:8], e)
                return None

            child_pages_found: list[str] = []

            # Prima passata: match diretto tra i child_page
            for block in children:
                b_type = block.get("type", "")
                b_id = block.get("id", "")
                if b_type == "child_page":
                    title = block.get("child_page", {}).get("title", "") or ""
                    if not title or title.strip().lower() in ("", "untitled"):
                        title = _fetch_page_title(b_id) or title
                    child_pages_found.append(title)
                    if title.lower().strip() == _DATABASES_SUBPAGE_NAME:
                        logger.info("[Discovery] Sub-page 'Databases' trovata (depth=%d): %s", depth, b_id)
                        return b_id

            # Seconda passata: ricorsione in layout block e child_page non-leaf
            for block in children:
                b_type = block.get("type", "")
                b_id = block.get("id", "")
                if b_type in _LAYOUT_BLOCK_TYPES:
                    found = _find_databases_subpage_id(b_id, depth + 1)
                    if found:
                        return found
                elif b_type == "child_page" and depth < 5:
                    title = block.get("child_page", {}).get("title", "") or ""
                    title_low = title.lower().strip()
                    # Entra solo nelle pagine container, non in quelle di contenuto
                    if title_low not in _LEAF_PAGE_TITLES:
                        found = _find_databases_subpage_id(b_id, depth + 1)
                        if found:
                            return found

            if depth == 0:
                logger.warning(
                    "[Discovery] Sub-page 'Databases' non trovata. "
                    "Child pages root (%d blocchi totali): %s",
                    len(children),
                    child_pages_found or "(nessuna)",
                )
            return None

        def _discover_from_databases_page(databases_page_id: str) -> None:
            """Mappa i child_database discendenti della pagina 'Databases'.

            Attraversa anche i blocchi layout per gestire template con DB
            organizzati in colonne/toggle. Recupera il titolo reale via
            databases.retrieve() quando il campo del blocco è vuoto.
            """
            def _walk(bid: str, depth: int = 0) -> None:
                if depth > 3:
                    return
                try:
                    children = client.blocks.children.list(block_id=bid).get("results", [])
                except Exception as e:
                    logger.warning("[Discovery] Errore lettura blocco %s: %s", bid[:8], e)
                    return
                for block in children:
                    b_type = block.get("type", "")
                    if b_type == "child_database":
                        db_id = block["id"]
                        title = block.get("child_database", {}).get("title", "") or ""
                        if not title or title.strip().lower() in ("", "untitled"):
                            title = _fetch_db_title(db_id) or title
                        if not title:
                            continue
                        title_low = title.lower().strip()
                        if title not in all_candidates:
                            all_candidates.append(title)
                        matched_key = _match_name(title_low)
                        if matched_key and matched_key not in discovered:
                            discovered[matched_key] = db_id
                            logger.info("[Discovery] DB reale trovato: '%s' → %s", title, matched_key)
                    elif b_type in _LAYOUT_BLOCK_TYPES:
                        _walk(block["id"], depth + 1)

            try:
                _walk(databases_page_id)
            except Exception as e:
                logger.warning("[Discovery] Errore lettura pagina Databases: %s", e)

        # ---------------------------------------------------------------------------
        # STRATEGIA PRINCIPALE: template_page_id → Databases sub-page → child_database
        #
        # Quando l'utente fa OAuth con il template Moneo, Notion restituisce
        # duplicated_template_id = ID della root page duplicata nel suo workspace.
        # Il percorso reale è:
        #   root → column_list → column → synced_block → Menu (child_page)
        #        → Databases (child_page) → 7 child_database reali con titoli
        #
        # Se template_page_id non è disponibile, cerchiamo la root per nome.
        # ---------------------------------------------------------------------------
        root_id: str | None = None
        if template_page_id:
            root_id = template_page_id
            logger.info("[Discovery] Root = template_page_id: %s", root_id)
        else:
            # Fallback: cerca per nome (setup manuale senza template)
            try:
                results = client.search(
                    query=_ROOT_PAGE_NAME,
                    filter={"value": "page", "property": "object"},
                    page_size=10,
                ).get("results", [])
                for obj in results:
                    props = obj.get("properties", {})
                    for p in props.values():
                        if p.get("type") == "title":
                            t = "".join(x.get("plain_text", "") for x in p.get("title", []))
                            if t.strip().lower() == _ROOT_PAGE_NAME.lower():
                                root_id = obj["id"]
                                logger.info("[Discovery] Root trovata via search: %s", root_id)
                                break
                    if root_id:
                        break
            except Exception as e:
                logger.debug("[Discovery] Search root fallita: %s", e)

        if root_id:
            databases_page_id = _find_databases_subpage_id(root_id)
            if databases_page_id:
                _discover_from_databases_page(databases_page_id)
                found = len(discovered)
                logger.info("[Discovery] Traversal completato: %d/7 DB trovati.", found)
                if found >= 7:
                    return discovered, all_candidates
                # Trovati alcuni ma non tutti: continua con fallback
                logger.warning("[Discovery] Solo %d/7 DB trovati via traversal, provo fallback.", found)
            else:
                logger.warning("[Discovery] Sub-page 'Databases' non trovata nella struttura.")

        # Se abbiamo template_page_id ma la traversal ha fallito → stop qui.
        # Non eseguire mai la global search quando il template è noto: potrebbe
        # trovare DB omonimi nel template originale e far scrivere nei posti sbagliati.
        if template_page_id:
            logger.warning(
                "[Discovery] Traversal fallita sul template dell'utente (%d/7 DB). "
                "Assicurati che tutte le pagine siano condivise con l'integrazione.",
                len(discovered),
            )
            return discovered, all_candidates

        # FALLBACK: Ricerca Globale (solo se NON c'è template_page_id).
        # Usata quando l'utente configura i DB manualmente senza usare il template.
        try:
            logger.info("[Discovery] Nessun template_page_id — ricerca globale nel workspace...")
            search_results = client.search(page_size=100).get("results", [])

            for obj in search_results:
                o_type = obj.get("object")
                o_id = obj.get("id")
                title = ""

                if o_type == "database":
                    title_list = obj.get("title", [])
                    title = "".join([t.get("plain_text", "") for t in title_list])
                elif o_type == "page":
                    props = obj.get("properties", {})
                    for p in props.values():
                        if p.get("type") == "title":
                            title = "".join([t.get("plain_text", "") for t in p.get("title", [])])
                            break

                if not title: continue
                title_low = title.lower().strip()

                if o_type == "database":
                    if title not in all_candidates:
                        all_candidates.append(title)
                    matched_key = _match_name(title_low)
                    if matched_key and matched_key not in discovered:
                        discovered[matched_key] = o_id
                        logger.info("[Discovery] Trovato DB (global): %s", title)
                elif o_type == "page" and ("database" in title_low or "finance" in title_low):
                    _scan_recursive(o_id, depth=1)

        except Exception as e:
            logger.error("[Discovery] Errore critico nella ricerca globale: %s", e)

        return discovered, all_candidates

    @staticmethod
    def discover_db_schemas(access_token: str, db_bindings: dict) -> dict[str, dict]:
        """Recupera lo schema (proprietà + title property) dei 7 DB con auto-mapping."""
        client = Client(auth=access_token)
        result: dict[str, dict] = {}

        all_db_keys = (
            "expense_db_id", "income_db_id", "categories_db_id", 
            "monthly_balance_db_id", "accounts_db_id", "subscriptions_db_id",
            "pay_transfer_db_id"
        )

        for db_key in all_db_keys:
            db_id = db_bindings.get(db_key)
            if not db_id:
                continue

            try:
                db = client.databases.retrieve(database_id=db_id)
                raw_properties = db.get("properties", {}) or {}
                
                # Se il DB è una "linked database view", properties sarà vuoto.
                # In quel caso seguiamo data_sources per trovare il DB originale con le proprietà.
                if not raw_properties:
                    data_sources = db.get("data_sources", [])
                    if data_sources:
                        real_db_id = data_sources[0].get("id")
                        if real_db_id:
                            try:
                                real_db = client.databases.retrieve(database_id=real_db_id)
                                raw_properties = real_db.get("properties", {}) or {}
                                # Aggiorniamo anche l'ID del db al quello reale per gli inserimenti
                                db_id = real_db_id
                            except Exception as follow_err:
                                logger.warning("Impossibile leggere il DB sorgente '%s': %s", real_db_id, follow_err)

                # Se le properties sono ancora vuote (DB sorgente 404 o non condiviso),
                # il setup form usa SCHEMA_DEFAULTS come fallback — nessuna azione richiesta.
                if not raw_properties:
                    logger.warning(
                        "Schema DB '%s' non disponibile: properties vuote e sorgente non accessibile. "
                        "Il form userà gli schemi di default.",
                        db_key,
                    )
                
                # 1. Estrarre i tipi e metadati (es. opzioni select)
                properties_map = {}
                for prop_name, prop_meta in raw_properties.items():
                    p_type = prop_meta.get("type") or "unknown"
                    p_info = {"type": p_type}
                    
                    if p_type == "select":
                        p_info["options"] = [o["name"] for o in prop_meta.get("select", {}).get("options", [])]
                    elif p_type == "multi_select":
                        p_info["options"] = [o["name"] for o in prop_meta.get("multi_select", {}).get("options", [])]
                    
                    properties_map[prop_name] = p_info

                # 2. Eseguire Auto-Mapping Intelligente
                mapped = {}
                
                # Regole generali per trovare i campi logici basandosi sul tipo
                for p_name, p_info in properties_map.items():
                    p_type = p_info["type"]
                    p_name_low = p_name.lower()
                    
                    if p_type == "title":
                        mapped["name"] = p_name
                    elif p_type == "select":
                        # Accounts DB: campo tipo conto (es. "Type", "Account type", "Tipo")
                        if db_key == "accounts_db_id":
                            if "type" in p_name_low or "tipo" in p_name_low:
                                mapped["account_type"] = p_name
                        # Subscriptions DB: campo tipo abbonamento (es. "Type", "Tipo", "Frequenza")
                        elif db_key == "subscriptions_db_id":
                            if "type" in p_name_low or "tipo" in p_name_low or "frequen" in p_name_low:
                                mapped["sub_type"] = p_name
                        # Income DB: campo tipo entrata (es. "Income Type", "Tipo entrata", "Tipo")
                        elif db_key == "income_db_id":
                            if "income" in p_name_low or "tipo" in p_name_low or "type" in p_name_low:
                                mapped["income_type"] = p_name
                    elif p_type == "number":
                        # Accounts DB: distinguiamo initial_amount dagli altri numeri
                        if db_key == "accounts_db_id" and ("initial" in p_name_low or "iniziale" in p_name_low):
                            mapped["initial_amount"] = p_name
                        # Subscriptions DB: importo abbonamento
                        elif db_key == "subscriptions_db_id" and ("amount" in p_name_low or "importo" in p_name_low or "cost" in p_name_low):
                            mapped["sub_amount"] = p_name
                        elif "importo" in p_name_low or "amount" in p_name_low or "cost" in p_name_low or "prezzo" in p_name_low:
                            mapped["amount"] = p_name
                        elif "amount" not in mapped: # Fallback al primo numero trovato se non c'è match testuale
                            mapped["amount"] = p_name
                    elif p_type == "date":
                        if "data" in p_name_low or "date" in p_name_low or "month" in p_name_low or "mese" in p_name_low:
                            mapped["date"] = p_name
                        elif "date" not in mapped:
                            mapped["date"] = p_name
                    elif p_type == "relation":
                        # Cerchiamo di capire a cosa punta (opzionale, basato sui nomi per ora)
                        if "cat" in p_name_low: mapped["rel_category"] = p_name
                        if "conto" in p_name_low or "account" in p_name_low:
                            if "from" in p_name_low: mapped["rel_account_from"] = p_name
                            elif "to" in p_name_low: mapped["rel_account_to"] = p_name
                            else: mapped["rel_account"] = p_name
                        if "monthly" in p_name_low or "bilancio" in p_name_low or "balance" in p_name_low:
                            mapped["rel_monthly_balance"] = p_name

                # Se manca il campo "name" (title), cerchiamo il primo del tipo giusto
                if "name" not in mapped:
                    for p_name, p_info in properties_map.items():
                        if p_info["type"] == "title": 
                            mapped["name"] = p_name
                            break
                
                result[db_key] = {
                    "database_id": db_id,
                    "title_property": mapped.get("name"),
                    "properties": properties_map,
                    "mapped": mapped
                }
            except Exception as e:
                logger.warning("Impossibile leggere schema DB '%s': %s", db_key, e)
                result[db_key] = {
                    "database_id": db_id,
                    "title_property": None,
                    "properties": {},
                    "mapped": {},
                    "error": str(e),
                }

        return result

    def __init__(self, 
                 api_key: Optional[str] = None,
                 expense_db_id: Optional[str] = None,
                 income_db_id: Optional[str] = None,
                 categories_db_id: Optional[str] = None,
                 monthly_balance_db_id: Optional[str] = None,
                 accounts_db_id: Optional[str] = None,
                 subscriptions_db_id: Optional[str] = None,
                 pay_transfer_db_id: Optional[str] = None,
                 db_schemas: Optional[dict[str, dict]] = None):
    
        # Logica del "Fallback": 
        # Se passo un ID (es. dal DB), uso quello. 
        # Se passo None, vado a pescare quello di default nel .env (Config).
        self.notion_api_key = api_key or Config.NOTION_API_KEY
        self.expense_db_id = expense_db_id or Config.NOTION_EXPENSE_DATABASE_ID
        self.income_db_id = income_db_id or Config.NOTION_INCOME_DATABASE_ID
        self.categories_db_id = categories_db_id or Config.NOTION_CATEGORIES_DATABASE_ID
        self.monthly_balance_db_id = monthly_balance_db_id or Config.NOTION_MONTHLY_BALANCE_DATABASE_ID
        self.accounts_db_id = accounts_db_id or Config.NOTION_ACCOUNTS_DATABASE_ID
        self.subscriptions_db_id = subscriptions_db_id or Config.NOTION_SUBSCRIPTIONS_DATABASE_ID
        self.pay_transfer_db_id = pay_transfer_db_id or Config.NOTION_PAY_TRANSFER_DATABASE_ID
        self._db_schemas = dict(db_schemas or {})

        # Inizializziamo il client ufficiale Notion con la chiave specifica di QUESTA istanza
        self._client = Client(auth=self.notion_api_key)
        
        # Caches
        self._data_source_cache: dict[str, str] = {}
        # _category_map rimosso: le categorie vivono in user_categories (DB locale)
        # e vengono lette tramite store in NotionStorage.

    def _resolve_title_property_name(self, db_key: str, db_id: str) -> str:
        """Ritorna il nome della property di tipo title per un database."""
        schema = self._db_schemas.get(db_key) or {}
        
        # 1. Prova dal mapping logico se presente
        mapped = schema.get("mapped") or {}
        if mapped.get("name"):
            return mapped["name"]
            
        # 2. Prova dalla property title_property legacy
        title_property = schema.get("title_property")
        if title_property:
            return title_property

        default_name = "Name"
        if not db_id:
            return default_name

        try:
            db = self._client.databases.retrieve(database_id=db_id)
            props = db.get("properties", {}) or {}
            for prop_name, prop_meta in props.items():
                if prop_meta.get("type") == "title":
                    title_property = prop_name
                    break

            if not title_property:
                return default_name

            # Aggiorna la cache dello schema per le prossime chiamate
            if db_key not in self._db_schemas:
                self._db_schemas[db_key] = {}
            self._db_schemas[db_key]["title_property"] = title_property
            
            return title_property
        except Exception as e:
            logger.warning(f"Errore risoluzione title property per {db_key}: {e}")
            return default_name

    def _get_property_name(self, db_key: str, logical_field: str, fallback_config_key: str = None) -> str:
        """Helper per ottenere il nome reale della property Notion da uno schema mappato."""
        schema = self._db_schemas.get(db_key) or {}
        mapped = schema.get("mapped") or {}

        # 1. Mapping esplicito (più affidabile)
        if mapped.get(logical_field):
            return mapped[logical_field]

        # 2. Se il fallback config corrisponde a una property esistente, usalo
        properties = schema.get("properties") or {}
        if fallback_config_key and fallback_config_key in properties:
            return fallback_config_key

        # 3. Ricerca fuzzy nelle properties: cerca una chiave che contenga il logical_field
        #    (es. logical_field="account_type" → trova "Type" o "Account type")
        search_terms = logical_field.replace("_", " ").lower().split()
        for prop_name in properties:
            prop_low = prop_name.lower()
            if any(term in prop_low for term in search_terms):
                logger.debug(f"[_get_property_name] fuzzy match: {logical_field} → {prop_name}")
                return prop_name

        # 4. Fallback al valore Config (legacy/statico)
        return fallback_config_key or logical_field.capitalize()

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
    # Risoluzione categoria — usata come fallback quando lo store locale non è disponibile
    # ------------------------------------------------------------------
    def _resolve_category_from_notion(self, page_id: str) -> dict:
        """Risolve un page_id chiamando direttamente la Notion API (fallback).

        Usato solo quando non è disponibile lo store locale (es. durante il bootstrap).
        In condizioni normali la risoluzione avviene da user_categories via NotionStorage.
        """
        db_id = self.categories_db_id
        if not db_id:
            return {"name": "Sconosciuta", "average": 0.0}
        try:
            page = self._client.pages.retrieve(page_id=page_id)
            props = page.get("properties", {})
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
                        if f_val.get("type") == "number":
                            average_val = float(f_val.get("number") or 0.0)
                    elif ptype == "number":
                        average_val = float(prop.get("number") or 0.0)
            return {"name": name, "average": average_val}
        except Exception as e:
            logger.warning("Impossibile risolvere categoria %s: %s", page_id[:8], e)
            return {"name": "Sconosciuta", "average": 0.0}

    # ------------------------------------------------------------------
    # Parsing spese
    # ------------------------------------------------------------------
    def _parse_expense_page(self, page: dict, category_resolver=None) -> Optional[dict]:
        """Converte una pagina Notion del database Expense in {date, category, name, amount}.

        category_resolver: callable(page_id) → {name, average}
        Se None, fa una chiamata Notion API per ogni categoria (solo fallback).
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
                    resolver = category_resolver or self._resolve_category_from_notion
                    cat_info = resolver(cat_page_id)
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
        category_resolver=None,
    ) -> list[dict]:
        """
        Recupera tutte le transazioni dal database Expense.

        Returns:
            Lista di dict {date, category, name, amount} ordinata per data.
        """
        logger.info(
            f"Estrazione Expense [{start_date or 'inizio'} → {end_date or 'oggi'}]"
        )

        # 1. Risolvi data_source_id
        ds_id = self._get_data_source_id(self.expense_db_id)

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
                parsed = self._parse_expense_page(page, category_resolver)
                if parsed:
                    all_results.append(parsed)

        all_results.sort(key=lambda x: x["date"])
        logger.info(f"Spese estratte: {len(all_results)} transazioni")
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
        db_id = self.monthly_balance_db_id
        if not db_id:
            logger.warning("Monthly Balance Database ID non configurato.")
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
            "id": page.get("id", ""),
            "year": mb_date.year,
            "month": mb_date.month,
            "net_savings": float(net_savings),
            "label": label,
        }

    def _resolve_monthly_balance(self, target_date: date) -> Optional[str]:
        """Trova il page_id del record Monthly Balance corrispondente per mese e anno."""
        for b in self.fetch_monthly_balances():
            if b["year"] == target_date.year and b["month"] == target_date.month:
                return b["id"]
        return None

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
        db_id = self.income_db_id
        if not db_id:
            logger.warning("Income Database ID non configurato.")
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

        # --- INCOME TYPE ---
        income_type_col = self._get_property_name("income_db_id", "income_type", "Income Type")
        income_type_prop = props.get(income_type_col, {})
        income_type_val = income_type_prop.get("select") or {}
        income_type = income_type_val.get("name")

        return {"date": tx_date, "name": name, "amount": amount, "income_type": income_type}

    # ------------------------------------------------------------------
    # Fetch Accounts
    # ------------------------------------------------------------------
    def fetch_accounts(self) -> list[dict]:
        """
        Recupera il saldo corrente da tutti i conti nel database Accounts.

        Returns:
            Lista di dict {name, current_balance}.
        """
        db_id = self.accounts_db_id
        if not db_id:
            logger.warning("Accounts Database ID non configurato.")
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

        return {
            "id": page_id,
            "name": name,
            "current_balance": float(current_balance)
        }

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

        numeric = self._extract_numeric_from_notion_property(prop)
        
        if numeric is None and page_id and prop.get("id"):
            prop_value = self._retrieve_page_property_with_retry(
                page_id=page_id,
                property_id=prop["id"],
            )
            numeric = self._extract_numeric_from_notion_property(prop_value)

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
            if val is None:
                return 0.0
            return float(val) if isinstance(val, (int, float)) else None

        if ptype == "rollup":
            rollup_val = prop.get("rollup", {})
            if rollup_val.get("type") == "number":
                val = rollup_val.get("number")
                if val is None:
                    return 0.0
                return float(val) if isinstance(val, (int, float)) else None
            return None

        if ptype != "formula":
            return None

        formula_val = prop.get("formula", {})
        ftype = formula_val.get("type", "")

        if ftype == "number":
            val = formula_val.get("number")
            if val is None:
                return 0.0
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
    # Write: creazione nuova spesa
    # ------------------------------------------------------------------
    def get_category_names(self) -> list[str]:
        """Restituisce i nomi delle categorie via Notion API (fallback senza store locale)."""
        db_id = self.categories_db_id
        if not db_id:
            return []
        try:
            ds_id = self._get_data_source_id(db_id)
            names = []
            has_more = True
            cursor = None
            while has_more:
                resp = self._query_with_retry(ds_id, {}, cursor)
                for page in resp.get("results", []):
                    for prop in page.get("properties", {}).values():
                        if prop.get("type") == "title":
                            rt = prop.get("title", [])
                            if rt:
                                names.append(rt[0].get("plain_text", ""))
                has_more = resp.get("has_more", False)
                cursor = resp.get("next_cursor")
            return [n for n in names if n]
        except Exception as e:
            logger.warning("Impossibile caricare nomi categorie da Notion: %s", e)
            return []

    def _resolve_category_by_name(self, category_name: str, page_id_override: Optional[str] = None) -> Optional[str]:
        """Risolve un nome categoria in page_id.

        Se page_id_override è fornito (da store locale), lo usa direttamente.
        Altrimenti fa una fetch live da Notion API (fallback).
        """
        if page_id_override:
            return page_id_override
        # Fallback: fetch live da Notion API
        db_id = self.categories_db_id
        if not db_id:
            return None
        try:
            ds_id = self._get_data_source_id(db_id)
            has_more = True
            cursor = None
            while has_more:
                resp = self._query_with_retry(ds_id, {}, cursor)
                for page in resp.get("results", []):
                    page_id = page["id"]
                    for prop in page.get("properties", {}).values():
                        if prop.get("type") == "title":
                            rt = prop.get("title", [])
                            if rt:
                                name = rt[0].get("plain_text", "")
                                if name.lower() == category_name.lower():
                                    return page_id
                                if category_name.lower() in name.lower() or name.lower() in category_name.lower():
                                    return page_id
                has_more = resp.get("has_more", False)
                cursor = resp.get("next_cursor")
        except Exception as e:
            logger.warning("Impossibile risolvere categoria '%s' da Notion: %s", category_name, e)
        return None

    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: Optional[str] = None,
        account_id: Optional[str] = None,
        _category_page_id: Optional[str] = None,
    ) -> dict:
        """
        Crea una nuova page nel database Expense.

        Args:
            expense_date: Data della spesa
            amount: Importo (positivo)
            name: Descrizione della spesa
            category_name: Nome della categoria (verrà risolta in page_id)
            account_id: Page ID del conto corrente (opzionale)

        Returns:
            dict con i dati della page creata
        """
        # Risoluzione nomi proprietà dallo schema
        col_date = self._get_property_name("expense_db_id", "date", Config.NOTION_COL_DATE)
        col_amount = self._get_property_name("expense_db_id", "amount", Config.NOTION_COL_AMOUNT)
        col_name = self._get_property_name("expense_db_id", "name", Config.NOTION_COL_NAME)
        col_category = self._get_property_name("expense_db_id", "rel_category", Config.NOTION_COL_CATEGORY)
        col_account = self._get_property_name("expense_db_id", "rel_account", Config.NOTION_COL_ACCOUNT)

        properties = {
            col_date: {
                "date": {"start": expense_date.isoformat()}
            },
            col_amount: {
                "number": abs(float(amount))
            },
            col_name: {
                "title": [
                    {
                        "text": {"content": name}
                    }
                ]
            },
        }

        # Risolvi la categoria in un page_id per la relation
        # _category_page_id viene da store locale (NotionStorage); fallback su Notion API
        if category_name:
            cat_page_id = self._resolve_category_by_name(category_name, page_id_override=_category_page_id)
            if cat_page_id:
                properties[col_category] = {
                    "relation": [{"id": cat_page_id}]
                }
                logger.info(f"Categoria '{category_name}' risolta in page_id {cat_page_id[:8]}...")
            else:
                logger.warning(f"Categoria '{category_name}' non trovata nel database Categories.")

        # Risolvi il conto 
        if account_id:
            properties[col_account] = {
                "relation": [{"id": account_id}]
            }

        # Risolvi Monthly Balance
        mb_id = self._resolve_monthly_balance(expense_date)
        if mb_id:
            col_mb = self._get_property_name("expense_db_id", "rel_monthly_balance", "Monthly Balance")
            properties[col_mb] = {
                "relation": [{"id": mb_id}]
            }
            logger.info(f"Relazione Monthly Balance ({expense_date.strftime('%m/%Y')}) risolta in page_id {mb_id[:8]}...")
        else:
            logger.warning(f"Attenzione: nessun Monthly Balance trovato per {expense_date.strftime('%m/%Y')}")

        logger.info(
            f"Creazione spesa su Notion: {name} — €{amount:.2f} — "
            f"{expense_date.isoformat()} — cat: {category_name or 'nessuna'} — conto_id: {account_id or 'nessuno'}"
        )

        result = self._client.pages.create(
            parent={"database_id": self.expense_db_id},
            properties=properties,
        )

        logger.info(f"Spesa creata con successo: page_id={result['id'][:8]}...")
        return result


    # ------------------------------------------------------------------
    # Write: creazione nuova entrata
    # ------------------------------------------------------------------
    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: Optional[str] = None,
        income_type: Optional[str] = None,
    ) -> dict:
        """
        Crea una nuova page nel database Income.

        Args:
            income_date: Data dell'entrata
            amount: Importo (positivo)
            name: Descrizione dell'entrata
            account_id: Page ID del conto corrente (opzionale)
            income_type: Tipo di entrata (es. "Stipendio", "Bonus", "Regalo") — opzionale

        Returns:
            dict con i dati della page creata
        """
        # Risoluzione nomi proprietà dallo schema
        col_date = self._get_property_name("income_db_id", "date", Config.NOTION_COL_DATE)
        col_amount = self._get_property_name("income_db_id", "amount", Config.NOTION_COL_AMOUNT)
        col_name = self._get_property_name("income_db_id", "name", Config.NOTION_COL_NAME)
        col_account = self._get_property_name("income_db_id", "rel_account", Config.NOTION_COL_ACCOUNT)

        col_misc = self._get_property_name("income_db_id", "misc", Config.NOTION_INCOME_COL_MISC)

        properties = {
            col_date: {
                "date": {"start": income_date.isoformat()}
            },
            col_amount: {
                "number": abs(float(amount))
            },
            col_name: {
                "title": [
                    {
                        "text": {"content": name}
                    }
                ]
            },
            col_misc: {
                "rich_text": [{"text": {"content": name}}]
            },
        }

        # Risolvi il conto
        if account_id:
            properties[col_account] = {
                "relation": [{"id": account_id}]
            }

        # Income Type (select)
        if income_type:
            col_income_type = self._get_property_name("income_db_id", "income_type", "Income Type")
            properties[col_income_type] = {
                "select": {"name": income_type}
            }

        # Risolvi Monthly Balance
        mb_id = self._resolve_monthly_balance(income_date)
        if mb_id:
            col_mb = self._get_property_name("income_db_id", "rel_monthly_balance", "Monthly Balance")
            properties[col_mb] = {
                "relation": [{"id": mb_id}]
            }
        else:
            logger.warning(f"Attenzione: nessun Monthly Balance trovato per {income_date.strftime('%m/%Y')}")

        logger.info(
            f"Creazione introito su Notion: {name} — €{amount:.2f} — "
            f"{income_date.isoformat()} — tipo: {income_type or 'nessuno'} — conto_id: {account_id or 'nessuno'}"
        )

        # Spediamo la entry al db
        result = self._client.pages.create(
            parent={"database_id": self.income_db_id},
            properties=properties,
        )

        logger.info(f"Introito creato con successo: page_id={result['id'][:8]}...")
        return result

    # ------------------------------------------------------------------
    # Write: creazione generica (per Setup Form Dinamico)
    # ------------------------------------------------------------------
    def create_database_item(self, database_id: str, properties_data: dict) -> dict:
        """
        Crea un elemento in un database Notion con proprietà arbitrarie.
        Gestisce la formattazione corretta dei tipi Notion (title, number, etc.).
        """
        logger.info(f"Creazione elemento nel DB {database_id[:8]}...")
        return self._client.pages.create(
            parent={"database_id": database_id},
            properties=properties_data
        )

    # ------------------------------------------------------------------
    # Write: creazione elementi setup (accounts/categories/subscriptions)
    # ------------------------------------------------------------------
    def create_account(self, account_name: str,
                       initial_amount: float = None,
                       account_type: str = None) -> dict:
        """Crea un conto nel database Accounts usando la title property corretta."""
        if not self.accounts_db_id:
            raise ValueError("Accounts database non configurato")

        title_property = self._resolve_title_property_name("accounts_db_id", self.accounts_db_id)
        properties = {
            title_property: {
                "title": [{"text": {"content": account_name}}]
            }
        }
        if initial_amount is not None:
            col = self._get_property_name("accounts_db_id", "initial_amount", Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT)
            properties[col] = {"number": float(initial_amount)}
        if account_type:
            col = self._get_property_name("accounts_db_id", "account_type", Config.NOTION_ACCOUNTS_COL_TYPE)
            properties[col] = {"select": {"name": account_type}}
        return self._client.pages.create(
            parent={"database_id": self.accounts_db_id},
            properties=properties,
        )

    def create_category(self, category_name: str) -> dict:
        """Crea una categoria nel database Categories usando la title property corretta."""
        if not self.categories_db_id:
            raise ValueError("Categories database non configurato")

        title_property = self._resolve_title_property_name("categories_db_id", self.categories_db_id)
        properties = {
            title_property: {
                "title": [{"text": {"content": category_name}}]
            }
        }
        return self._client.pages.create(
            parent={"database_id": self.categories_db_id},
            properties=properties,
        )

    def create_subscription(self, subscription_name: str,
                            sub_type: str = None,
                            amount: float = None,
                            category_id: str = None,
                            account_id: str = None,
                            last_billed: str = None) -> dict:
        """Crea un abbonamento nel database Subscriptions usando la title property corretta."""
        if not self.subscriptions_db_id:
            raise ValueError("Subscriptions database non configurato")

        title_property = self._resolve_title_property_name("subscriptions_db_id", self.subscriptions_db_id)
        properties = {
            title_property: {
                "title": [{"text": {"content": subscription_name}}]
            }
        }
        if sub_type:
            col = self._get_property_name("subscriptions_db_id", "sub_type", Config.NOTION_SUB_COL_TYPE)
            properties[col] = {"select": {"name": sub_type}}
        if amount is not None:
            col = self._get_property_name("subscriptions_db_id", "amount", Config.NOTION_SUB_COL_AMOUNT)
            properties[col] = {"number": float(amount)}
        if category_id:
            col = self._get_property_name("subscriptions_db_id", "rel_category", Config.NOTION_SUB_COL_CATEGORY)
            properties[col] = {"relation": [{"id": category_id}]}
        if account_id:
            col = self._get_property_name("subscriptions_db_id", "rel_account", Config.NOTION_SUB_COL_ACCOUNT)
            properties[col] = {"relation": [{"id": account_id}]}
        if last_billed:
            col = self._get_property_name("subscriptions_db_id", "last_billed", Config.NOTION_SUB_COL_LAST_BILLED)
            properties[col] = {"date": {"start": last_billed}}
        return self._client.pages.create(
            parent={"database_id": self.subscriptions_db_id},
            properties=properties,
        )


    # ------------------------------------------------------------------
    # Test connessione
    # ------------------------------------------------------------------
    def test_connection(self) -> str:
        """Verifica la connessione e lo stato di accesso a tutti i database."""
        lines = []
        databases = [
            ("Expense", self.expense_db_id),
            ("Categories", self.categories_db_id),
            ("Monthly Balance", self.monthly_balance_db_id),
            ("Income", self.income_db_id),
            ("Accounts", self.accounts_db_id),
            ("Subscriptions", self.subscriptions_db_id),
            ("Pay/Transfer", self.pay_transfer_db_id),
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

