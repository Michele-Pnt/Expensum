# Schema Logico della Base di Dati — Expensum

**Progetto:** Expensum — Bot Telegram e webapp per la gestione delle finanze personali  
**Autore:** Michele Pinotti  
**Data:** Giugno 2026  
**DBMS target:** PostgreSQL 16
**ORM:** SQLAlchemy 2.0 

---

## 1. Analisi dei Requisiti

Expensum è un'applicazione multi-utente che permette a ciascun utente di:

- registrare **spese** e **entrate** su più **conti** bancari/contanti
- classificare le transazioni per **categorie** personalizzate con budget mensile
- gestire **abbonamenti ricorrenti**
- accedere e modificare la propria storia finanziaria via bot Telegram e webapp Next.js

---

## 2. Schema Concettuale (Modello E-R)

### 2.1 Entità Principali

| Entità | Descrizione |
|---|---|
| **USER** | Utente registrato, identificato dall'ID chat Telegram |
| **ACCOUNT** | Conto corrente, conto contanti o carta di credito dell'utente |
| **USER_CATEGORY** | Categoria di spesa personalizzata per utente |
| **EXPENSE** | Singola transazione di uscita |
| **INCOME** | Singola transazione di entrata |
| **SUBSCRIPTION** | Abbonamento ricorrente (es. Netflix, Spotify) |

### 2.2 Relazioni principali

```
USER ──(1,N)──< ACCOUNT          un utente ha N conti
USER ──(1,N)──< USER_CATEGORY    un utente ha N categorie
USER ──(1,N)──< EXPENSE          un utente ha N spese
USER ──(1,N)──< INCOME           un utente ha N entrate
USER ──(1,N)──< SUBSCRIPTION     un utente ha N abbonamenti
EXPENSE >──(N,1)── ACCOUNT          una spesa è addebitata su 1 conto (opt.)
EXPENSE >──(N,1)── USER_CATEGORY    una spesa appartiene a 1 categoria (opt.)
INCOME  >──(N,1)── ACCOUNT          un'entrata è accreditata su 1 conto
SUBSCRIPTION >──(N,1)── ACCOUNT          un abbonamento è su 1 conto (opt.)
SUBSCRIPTION >──(N,1)── USER_CATEGORY    un abbonamento ha 1 categoria (opt.)
```

---

## 3. Schema Logico Relazionale

users (<u>chat_id</u>, username, email, password_hash, storage_backend, notion_access_token, notion_workspace_id, expense_db_id, income_db_id, categories_db_id, monthly_balance_db_id, accounts_db_id, subscriptions_db_id, pay_transfer_db_id, accounts_schema_json, categories_schema_json, subscriptions_schema_json, preferred_language, currency, timezone, lifestyle_json, monthly_budget, notification_time, notifications_enabled, is_active, created_at, setup_status, setup_completed_at, onboarding_step, onboarding_completed_at, telegram_chat_id, pinned_dashboard_msg_id)

accounts (<u>id</u>, <u><span style="color:red">user_id</span></u>, name, opening_balance, currency, account_type)

user_categories (<u>id</u>, <u><span style="color:red">user_id</span></u>, name, monthly_budget)

expenses (<u>id</u>, <u><span style="color:red">user_id</span></u>, expense_date, amount, name, <u><span style="color:red">category_id</span></u>, category_name, <u><span style="color:red">account_id</span></u>, created_at)

incomes (<u>id</u>, <u><span style="color:red">user_id</span></u>, income_date, amount, name, <u><span style="color:red">account_id</span></u>, income_type, created_at)

subscriptions (<u>id</u>, <u><span style="color:red">user_id</span></u>, name, amount, last_billed, sub_type, <u><span style="color:red">account_id</span></u>, <u><span style="color:red">category_id</span></u>, created_at)

## 4. Vincoli di Integrità

### 4.1 Chiavi primarie

| Tabella | Chiave primaria |
|---|---|
| `users` | `chat_id` (VARCHAR — ID Telegram) |
| `user_plans` | `chat_id` (FK su `users`) |
| `oauth_sessions` | `state` (token casuale) |
| `user_category_notion_links` | `category_id` (FK su `user_categories`) |
| Tutte le altre | `id` (INTEGER AUTOINCREMENT) |

### 4.2 Chiavi esterne

Le foreign key sono dichiarate con il comportamento default `NO ACTION`.

| Tabella | Attributo FK | Referenzia |
|---|---|---|
| `accounts` | `user_id` | `users(chat_id)` |
| `user_categories` | `user_id` | `users(chat_id)` |
| `expenses` | `user_id` | `users(chat_id)` |
| `expenses` | `category_id` | `user_categories(id)` |
| `expenses` | `account_id` | `accounts(id)` |
| `incomes` | `user_id` | `users(chat_id)` |
| `incomes` | `account_id` | `accounts(id)` |
| `subscriptions` | `user_id` | `users(chat_id)` |
| `subscriptions` | `account_id` | `accounts(id)` |
| `subscriptions` | `category_id` | `user_categories(id)` |


### 4.3 Vincoli di dominio (CHECK)

> **Nota:** questi vincoli non sono attualmente implementati come `CHECK CONSTRAINT` nel DB; sono validati a livello applicativo (Python). In uno schema logico "puro" sarebbero esprimibili come vincoli `CHECK`, raccomandazione per future migration.

| Tabella | Attributo | Dominio atteso |
|---|---|---|
| `users` | `storage_backend` | `'notion'` oppure `'postgres'` |
| `users` | `setup_status` | `'WAIT_ACCOUNTS'`, `'DONE'`, altri step |
| `expenses` | `amount` | `> 0` |
| `incomes` | `amount` | `> 0` |


## 5. Indici

| Tabella | Attributo/i | Tipo | Motivazione |
|---|---|---|---|
| `users` | `email` | UNIQUE INDEX | Login webapp e lookup per reset password |
| `user_categories` | `user_id` | INDEX | Lista categorie per utente (query frequente) |

## 6. Query SQL più importanti
