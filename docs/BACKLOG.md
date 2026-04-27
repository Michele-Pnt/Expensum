# BACKLOG — Moneo

## 🔥 In corso

Nessun task in corso.

---

## 🐛 Bug aperti

- [ ] ci sono dei bug sulla routine di auto gestione degli abbonamenti di utenti pro

---

## ✅ Completati

### 2026-04-26
- **Sistema Token Freemium**: implementazione `UserPlan`, tetti mensili (150k Free / 3M Pro), middleware in `bot.py` per limitare audio/foto agli utenti Free e scalare i token ad ogni azione AI.
- **Job Abbonamenti Automatici**: esecuzione notturna alle 04:00 (spostata su richiesta dell'utente), creazione automatica spese, aggiornamento saldo e notifica Telegram per utenti Pro.
- **Monthly Balance Automatico**: implementato `get_or_create_monthly_balance` per Notion e Postgres; le spese vengono ora collegate automaticamente al record del mese corretto (creandolo se necessario con nome in italiano).
- **Integrazione Storage**: aggiornato `FinancialStorage` e gli adapter Notion/Postgres per supportare `monthly_balance_id` opzionale in `create_expense`.
- **Nuovi Moduli**: `src/billing_utils.py` (logica date), `src/dashboard_message.py` (testo dashboard), `src/user_store.py` (modelli piani).
- **Analytics Zero Friction**: inserito pulsante `[📊 Apri Analytics]` nella dashboard pinnata `/status`.

### 2026-04-25 (aggiornamento)
- Fix bug: crash ambiente durante esecuzione test con Claude antigravity — risolto

### 2026-04-25
- `scripts/start_dev.sh`: script bash che avvia ngrok + bot Telegram + dashboard Flask in parallelo; aggiorna automaticamente `WEBAPP_BASE_URL` e `NOTION_REDIRECT_URI` nel `.env` con l'URL ngrok rilevato
- Modello dati esteso con migration Alembic (`d4e5f6a7b8c9_add_entity_fields`):
  - `Account.account_type` (String, nullable)
  - `UserCategory.monthly_budget` (Float, nullable)
  - `Subscription`: aggiunti campi `amount`, `sub_type`, `account_id`, `category_id`
- `PostgresStorage`: aggiunti metodi CRUD — `create_account`, `create_category`, `create_subscription`, `update_category`, `update_subscription`
- `UserStore`: aggiunti `get/set_pinned_dashboard_msg_id`, `get_user_categories_with_averages`, `delete_user_completely`, `get_user_subscriptions`
- `WorkspaceBootstrapper`: rimossi conti di default (`Conto Corrente`, `Contanti`) — l'utente li crea da mini app; rimosso riferimento a `/setup` nel messaggio di conferma
- Frontend `Sidebar` migrata da CSS Module a MUI (`Drawer`, `ListItem`, icone MUI); aggiunta voce "Chat (Moneo)" nella navigazione
- Rimossi `src/dashboard/aws_monitor.py` e `tests/test_aws.py` (AWS monitoring mai usato in produzione)
- Rimosso `.github/workflows/deploy.yml` (workflow deploy disattivato)

### 2026-04-23
- Mini app: campo `monthly_budget` visibile e modificabile nel form modifica categorie (fix bug "campo non si vede con il primo setup")
- Comando `/status`: invia e pinna la dashboard finanziaria in chat (saldi conti, abbonamenti con stima prossima rata, spese per categoria vs media storica); unpin automatico del messaggio precedente; `message_id` persistito in `UserStore`
- `src/dashboard_message.py` — nuovo modulo: costruisce il testo Markdown della dashboard; stima prossima rata abbonamento per tipo (mensile, annuale, settimanale, trimestrale, bimestrale)
- Comando `/modify` sostituisce `/setup` — apre la mini app completa per gestire conti, categorie e abbonamenti

### 2026-04-22
- Debug e fix flusso mini app utenti PostgreSQL:
  - `KeyError: 'current_balance'` al conferma spesa: `acc['current_balance']` → `acc['balance']` in `bot.py:814`
  - Mini app bloccata su sola tab Categorie: `user.setup_completed` (campo inesistente) → `user.setup_completed_at is None`; `mark_setup_completed` mai chiamato
  - Link post-login puntava a `/setup/miniapp` (404) → corretto in `/setup`
  - `url_for("setup_miniapp")` → `url_for("setup_form")` in `web_login`
- Rimosso comando `/setup`, aggiunto `/modify` che apre mini app completa via WebApp
- Dopo registrazione Postgres e Notion: bootstrap chiama `mark_setup_completed`, crea reg_token fresco e invia bottone "⚙️ Configura il tuo spazio" direttamente in Telegram
- Mini app sempre in modalità completa (tutte e 3 le tab visibili): rimossa logica `is_first_setup` da template e route Flask
- Mini app: aggiunto campo `balance` editabile nel form modifica account
- Mini app: aggiunto campo `amount` (importo mensile) per abbonamenti — colonna aggiunta al modello `Subscription`, migration automatica SQLite+PostgreSQL in `_ensure_sqlite_schema`, storage e API aggiornati

### 2026-04-21
- Sistemati 3 bug mini app Notion:
  - Saldo account non si aggiornava su Notion (chiave `balance` vs `initial_balance`)
  - Dropdown categorie nel form abbonamenti mostrava solo cache locale (ora fetch diretto da Notion)
  - `last_billed` non veniva passato correttamente (mancava `col_sub_last_billed` nel template)
- Form modifica account: rimosso campo saldo, aggiunto campo Tipo conto (select)
- `initial_amount` editabile solo alla creazione, non in modifica
- Setup iniziale nuovo utente: mostra solo tab Categorie (Conti e Abbonamenti nascosti finché `setup_completed_at` è null)
- Fix `is_first_setup`: usava `user.setup_completed` inesistente → corretto in `user.setup_completed_at is None`
- Fix comando `/start`: indicava `/registra` invece di `/registrati`
- Reset DB e ricreazione per test
- Sistema autenticazione email+password:
  - Aggiunti campi `email` e `password_hash` al modello `User` con migration automatica SQLite
  - `UserStore`: aggiunti `set_credentials()`, `get_user_by_email()`, `verify_password()` con bcrypt
  - `/auth/postgres`: ora raccoglie email+password via form HTML prima di creare l'utente
  - Route Flask `/login` (GET+POST) con sessione, redirect al mini app con reg_token fresco
  - Route Flask `/logout`
  - `FLASK_SECRET_KEY` letta da env per sessioni stabili tra restart
  - Comando Telegram `/login`: ConversationHandler email→password, elimina messaggio psw, invia link setup
  - Template `login.html` e `register_postgres.html`
  - Messaggio `/start` aggiornato: menziona `/registrati` e `/login`
- Endpoint update Notion: usa `NotionFinanceClient` con schemi per risolvere nomi colonna reali (fix account_type non aggiornato)
- `fetch_categories()` aggiunto a `NotionFinanceClient` (fetch diretto da Notion come `fetch_accounts`)
- `_parse_account_page` ora include `account_type` nel dict restituito
- Aggiunto `bcrypt` a `requirements.txt`
