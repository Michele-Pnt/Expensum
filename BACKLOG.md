# BACKLOG — Moneo

## 🔥 In corso

- [ ] Testare registrazione e login con backend PostgreSQL end-to-end
- [ ] Verificare i reindirizzamenti post-login (da Telegram e da web app) e correggerli se necessario

---

## 🐛 Bug aperti

- Reindirizzamenti dopo login non ancora validati: flusso Telegram (`/login` → setup link) e flusso web (`/login` → mini app) da testare su ambiente reale
- Flusso registrazione PostgreSQL (`/auth/postgres` form email+psw) non ancora testato su VPS

---

## ✅ Completati

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
