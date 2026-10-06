# Development setup

This guide covers local development. Use test accounts and credentials for
development and testing.

## Backend

Create and activate a Python 3.12 environment from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
cp .env.example .env
```

Set only the local configuration and provider credentials needed for your
work. The application supports PostgreSQL and a Notion storage integration;
the example configuration contains the current environment variable names.
Never commit `.env` or real provider credentials.

Run the Telegram bot with `python bot.py`. The Flask backend can be started
with `python src/dashboard/app.py` when its configuration is available.

Telegram account linking queues cross-account chat ID updates for a separate worker.
For local PostgreSQL development, start it in another terminal with
`python scripts/process_reassignment_jobs.py`; it uses `MIGRATION_DATABASE_URL` for
that privileged operation. Keep that credential out of the bot and dashboard processes.

## Frontend

```bash
cd frontend
npm ci
npm run dev
```

The local frontend is available at <http://localhost:3000>. Run its tests and
static checks with `npm test`, `npm run lint`, and `npm run typecheck`.

## Tests

From the repository root:

```bash
pytest -m unit
pytest
```

The standard suite uses mocks for external services. It should not require
provider credentials or send requests to live services. PostgreSQL-specific
tests use the optional local Docker setup:

```bash
cp .env.local.example .env.local
./scripts/dev_db.sh up
./scripts/dev_db.sh migrate
set -a && source .env.local && set +a
pytest -m pg
./scripts/dev_db.sh down
```

## Project structure

- `bot.py`, `main.py`, `src/`: Python application and integrations.
- `frontend/`: Next.js web application.
- `alembic/`: versioned database migrations.
- `tests/`: Python test suite.
- `docs/`: contributor-facing technical documentation.
