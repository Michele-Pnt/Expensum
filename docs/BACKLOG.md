# 📋 Backlog — Finance Agents

> File operativo. Contiene task completati, in corso, e bug aperti. Per la visione futura → ROADMAP.md

---

## 🔥 In corso

- [ ] **Testing nuovo sistema categorie + fix bug aperti** — testare end-to-end il nuovo sistema `user_categories` / `system_categories`, verificare `income_type`, risolvere i bug aperti elencati sotto. Domande architetturali da chiarire prima di procedere:
  - Perché `system_categories` non ha FK agli utenti?
  - Come si tracciano le spese per categoria per utente?
  - Ha senso avvisare l'utente se prova a registrare una spesa durante l'aggiornamento notturno delle categorie (capacità ridotte temporaneamente)?

---

## ✅ Completati

### 2026-04-18
- [x] Refactoring sistema categorie — rimossa tabella `categories`, aggiunte `system_categories` (32 categorie default condivise) e `user_categories` (per-utente, con `notion_page_id`, `average`, `synced_at`)
- [x] Migration Alembic `b2c3d4e5f6a7` — crea nuove tabelle, migra dati, dropa `categories`
- [x] Creato `src/category_sync.py` — `sync_categories_to_local()` (Notion), `compute_category_averages()` (Postgres), `refresh_category_averages()` (entry point unificata)
- [x] Rimossa `_category_map` da `NotionFinanceClient` — le categorie non vivono più in RAM per utente
- [x] `NotionStorage` riceve `store` + `user_id` — `get_category_names()`, `_resolve_category()`, `create_expense()` leggono da DB locale
- [x] Rimossa cache `_parsers` da `bot.py` — `_get_parser()` legge da `user_categories` (query SQL < 1ms, nessuna RAM occupata)
- [x] `_storage_clients` → `TTLCache(maxsize=200, ttl=1800)` — eviction automatica dopo 30 min inattività (VPS Hetzner CX23 4GB RAM)
- [x] Trigger A post-setup (app.py) — `refresh_category_averages()` chiamato dopo `bootstrap_workspace()` per entrambi i backend
- [x] Job notturno APScheduler alle 03:00 (bot.py) — aggiornamento medie categorie per tutti gli utenti attivi, sequenziale con 200ms sleep (VPS-friendly)
- [x] Aggiunto `cachetools>=5.3.0` a `requirements.txt`

### 2026-04-14
- [x] Transizione storage da Notion a PostgreSQL — implementato Repository Pattern con `FinancialStorage` ABC, `NotionStorage` adapter, `PostgresStorage`
- [x] Aggiornato flusso di registrazione utente per supportare campo `storage_backend`
- [x] Connessione PostgreSQL configurata — produzione su Hetzner CX23 self-hosted via Unix socket
- [x] Configurato Alembic con migration `f7b2c56cec79` applicata
- [x] `bot.py` e `main.py` aggiornati per usare `_get_storage()` invece di `_get_notion()`
- [x] Aggiunta colonna `Income Type` (select) al DB Notion Income — auto-categorizzazione AI via `expense_parser.py`, auto-mapping schema in `notion_client.py`, propagazione in tutti i layer
- [x] Migration Alembic `a1b2c3d4e5f6` per colonna `income_type` su tabella `incomes`
- [x] Fix bug: `income_type` non veniva salvato in `pending_expense` in `bot.py`
- [x] Messaggio di conferma entrata aggiornato per mostrare il tipo rilevato dall'AI

---

## 🐛 Bug aperti

- [ ] **test_discover_databases_strategy_1_with_template_id** — test di discovery Notion pre-esistente, non correlato alle modifiche recenti; da investigare e risolvere
- [ ] **Session management Postgres** — in `_get_storage()` la `Session` per utenti Postgres non viene mai chiusa esplicitamente; da implementare "Strada B" (session.close() dopo ogni operazione in `PostgresStorage`)
- [ ] **`cat_info` unused variable** — warning a `bot.py:482`, da rimuovere
- [ ] **Income Type non testato** — la nuova colonna è implementata ma non è stato verificato il flusso end-to-end su Notion e PostgreSQL

---

## 📦 Backlog (da pianificare)

- [ ] Test flusso registrazione su Telegram
