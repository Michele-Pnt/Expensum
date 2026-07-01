# Expensum — Project Audit per Collaboratori

> Documento conciso per onboarding tecnico. Ultimo aggiornamento: 2026-07-01.

---

## Cos'è

**Expensum** è un bot Telegram + web app SaaS per la gestione delle finanze personali.
L'utente manda una spesa via testo, foto scontrino o vocale → l'AI la analizza e la salva.
Include dashboard admin Flask (web), analytics avanzata (Next.js Mini App), report AI mensile/settimanale.

**Modello:** Freemium (Free 150k token/mese gratis | Pro 4,99€/mese).
**Stato:** In sviluppo attivo — infrastruttura completa, deployment imminente (Fase 2.4).

---

## Struttura cartelle

```
Finance-Agents/
├── bot.py                  # Entry point del bot Telegram — gestisce tutti i messaggi
├── main.py                 # Orchestratore pipeline report mensile (CLI)
├── config.py               # Carica e valida variabili d'ambiente dal .env
├── scheduler.py            # Daemon APScheduler — report automatico il 1° del mese
│
├── src/                    # Tutta la business logic
│   ├── expense_parser.py   # NLP → JSON strutturato (data, importo, categoria, nome)
│   ├── mistral_client.py   # Client Mistral Small 3.1 — report mensile e piani weekly/monthly
│   ├── notion_client.py    # Client Notion API (7 database per utente)
│   ├── telegram_client.py  # Invio messaggi/foto Telegram con auto-split 4096 char
│   ├── user_store.py       # ORM SQLAlchemy: users, usage, feedback, OAuth, piani
│   ├── data_processor.py   # Aggregazione pandas (report mensile + budget settimanale)
│   ├── forecaster.py       # Previsione spese mese prossimo (ottimistico/base/pessimistico)
│   ├── chart_generator.py  # Grafici matplotlib/seaborn → PNG → Telegram
│   ├── report_builder.py   # Builder report Telegram: mensile, settimanale, piano mensile
│   ├── rate_limiter.py     # Sliding window 10 msg/min per utente (anti-DoS, MAI disabilitare)
│   ├── input_sanitizer.py  # Anti-prompt-injection: 20+ regex su OCR e trascrizioni audio
│   ├── ocr_client.py       # Tesseract OCR locale — estrazione testo da foto scontrino
│   ├── category_sync.py    # Sync categorie Notion ↔ DB locale
│   ├── workspace_bootstrapper.py  # Init workspace nuovi utenti (categorie + conti default)
│   ├── billing_utils.py    # Calcolo date rinnovo abbonamenti
│   ├── dashboard_message.py # Testo Markdown per dashboard pinnata /status
│   │
│   ├── storage/            # Repository Pattern — astrazione backend finanziario
│   │   ├── base.py         # Interfaccia astratta FinancialStorage (ABC)
│   │   ├── models.py       # Modelli SQLAlchemy per backend PostgreSQL
│   │   ├── notion_storage.py    # Adapter FinancialStorage → Notion (backend attuale)
│   │   └── postgres_storage.py  # Adapter FinancialStorage → PostgreSQL (backend alternativo)
│   │
│   └── dashboard/
│       └── app.py          # Flask admin: utenti, feedback, log, OAuth, API Mini App
│
├── frontend/               # Next.js 16 — Mini App Telegram (analytics utente)
│   └── src/app/
│       ├── page.tsx        # Home / dashboard overview
│       ├── reports/        # Report AI salvati
│       ├── abbonamenti/    # Gestione abbonamenti
│       ├── chat/           # Chat RAG (placeholder Fase 3)
│       ├── onboarding/     # Setup iniziale utente
│       ├── feedback/       # Form feedback utente
│       ├── privacy/        # Privacy policy
│       └── terms/          # Termini di servizio
│
├── tests/                  # pytest — unit + integration + e2e
├── alembic/                # Migration SQLAlchemy (schema DB)
├── docs/                   # Documentazione tecnica completa
│   ├── Architecture.md     # Architettura dettagliata + documentazione moduli
│   ├── ROADMAP.md          # Roadmap strategica
│   ├── schema-logico-db.md # Schema DB completo
│   └── deploy.md           # Istruzioni deploy VPS
└── .github/workflows/      # CI/CD: test.yml (pytest) + deploy.yml (SSH → VPS)
```

---

## Stack tecnologico

| Layer | Tecnologia |
|---|---|
| Bot | python-telegram-bot ≥21 (webhook + long-polling) |
| AI parsing testo/foto | Mistral Small 3.1 — EU, GDPR-compliant |
| AI report/analisi | Mistral Small 3.1 (Chain-of-Thought — report mensile, piani weekly/monthly) |
| AI speech | Gemini 2.0 Vertex AI (solo Pro, region europe-west3) |
| AI chat RAG | Mistral Large 3 (Fase 3 — non ancora implementato) |
| OCR scontrini | Tesseract OCR (locale, zero data transfer) |
| ORM / DB | SQLAlchemy 2.0 + PostgreSQL (prod) / SQLite (dev) |
| Web admin | Flask 3.0 |
| Frontend utente | Next.js 16.2, React 19, TypeScript 5, recharts |
| Scheduling | APScheduler 3.10 |
| Retry | tenacity (exponential backoff su Mistral, Notion, Telegram) |
| Hosting | Netcup VPS Lite 1 G12s — 2 vCore, 4GB RAM, 80GB SSD, IPv4: REDACTED-IP |
| CI/CD | GitHub Actions → SSH deploy → systemd restart |

---

## Database

### DB applicativo (SQLAlchemy — locale)
Gestisce gli utenti del bot, non i loro dati finanziari.

| Tabella | Contenuto |
|---|---|
| `users` | Account utente, credenziali Notion/Postgres, stato setup, piano (free/pro) |
| `user_plans` | Token rimanenti, data reset, totali |
| `daily_usage` | Contatori giornalieri per utente: testo / voce / foto |
| `daily_metrics` | Metriche AI globali giornaliere (goal_completions, fallbacks) |
| `feedbacks` | Feedback utenti con stato risoluzione |
| `database_schemas` | Mapping schemi Notion per utente (db_key → notion_db_id) |
| `oauth_sessions` | Stato temporaneo flusso OAuth 2.0 Notion |
| `user_categories` | Mirror categorie per utente (con media storica spesa) |

### DB finanziario utente — due backend intercambiabili
Tutto il codice passa per `FinancialStorage` (ABC) — il backend è trasparente.

**Notion (backend attuale):** 7 database per utente — Spese, Entrate, Categorie, Conti, Abbonamenti, Trasferimenti, Bilancio mensile.

**PostgreSQL (backend alternativo):** tabelle `Expense`, `Income`, `Account`, `UserCategory`, `Subscription`, `MonthlyBalance`.

---

## Architettura — flusso messaggi

```
Utente Telegram
    │  testo / vocale / foto
    ▼
bot.py
    ├── rate_limiter.is_rate_limited()       # blocca se > 10 msg/min
    ├── input_sanitizer.sanitize_*()         # anti-prompt-injection
    ├── [foto] ocr_client.extract_text()     # OCR locale Tesseract
    ├── [audio] Gemini speech-to-text        # trascrizione audio
    ├── expense_parser.parse()               # Mistral: testo → JSON {data, importo, cat, nome}
    ├── mostra riepilogo + bottoni ✅/❌
    └── [confermato] storage.create_expense()
            ├── NotionStorage → notion_client → Notion API
            └── PostgresStorage → SQLAlchemy → PostgreSQL
```

**Report mensile** (`/monthly` o schedulato il 1°):
```
storage.fetch_* → DataProcessor → Forecaster → ChartGenerator → MistralClient → TelegramClient
```

---

## Sicurezza — punti chiave

- **Rate limiting:** sliding window 10 msg/min per utente — non disabilitare mai
- **Anti-prompt-injection:** `input_sanitizer.py` — 20+ regex IT/EN su OCR e audio prima dell'LLM
- **OAuth 2.0 Notion:** nessuna API key diretta — flusso OAuth ufficiale
- **Output strutturato:** Mistral risponde solo in JSON con schema fisso (difesa contro adversarial suffix)
- **No secret nel codice:** tutto via `.env` — non committare mai
- **Dati personali:** MAI loggare importi, API key, token Telegram

---

## Roadmap sintetica

| Fase | Stato | Descrizione |
|---|---|---|
| 1 — Core infrastruttura | ✅ Completata | PostgreSQL, Web App init, architettura multi-utente |
| 2.1 — MiniApp permanente | ✅ Completata | Gestione conti / categorie / abbonamenti |
| 2.2 — Logica avanzata | ✅ Completata | Token freemium, job notturno abbonamenti Pro, analytics |
| 2.3 — Web App Next.js | 🔴 In corso | Restyling, mascotte Moneo, pagine analytics/chat |
| 2.4 — Deployment | 🔴 Prossima | VPS Netcup ✅, dominio expensum.it ✅, go-live prod |
| 3 — AI Avanzata | 🔴 Futura | Agent RAG conversazionale (Mistral Large 3) |
| 4 — Mobile | 🔴 Futura | App mobile + notification listener bancario |
| 5 — Monetizzazione | 🔴 Futura | Stripe (decisione presa), beta pubblica |

**Goal business:** 10k€ netti entro 30/06/2027. Sprint dev blindato: 15 lug → 31 ago 2026.

---

## Come lavorare sul progetto

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # compilare manualmente

# Bot in locale (long-polling)
python bot.py

# Dashboard Flask admin
python src/dashboard/app.py

# Frontend Next.js
cd frontend && npm run dev

# Test (default: unit + integration)
pytest
pytest -m unit          # solo unit, velocissimo
pytest --cov=src        # con copertura
```

**Documentazione dettagliata moduli:** [architecture overview](Architecture.md)
**Schema DB completo:** [docs/schema-logico-db.md](schema-logico-db.md)
**Deploy VPS:** [deployment documentation](deploy.md)
