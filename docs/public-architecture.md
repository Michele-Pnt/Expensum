# Architecture overview

Expensum has a Python backend, a Next.js web application, and optional external
integrations. The Telegram bot and web application call backend services; the
backend contains authentication, transaction processing, analytics, and
storage adapters.

## Main components

- `bot.py` and `src/`: Telegram handlers, Flask routes, application services,
  integrations, and storage abstractions.
- `frontend/`: Next.js and React user interface. Backend requests are routed
  through the configured server-side API origin.
- `alembic/`: database schema migrations.
- `tests/`: unit and integration tests, with external APIs mocked.

## Storage and integrations

Financial storage is accessed through a shared storage contract, with
PostgreSQL and Notion adapters. Keep business logic independent of a specific
provider and keep provider-specific identifiers inside the corresponding
adapter.

Telegram, email delivery, and AI providers are external integrations. Tests
must mock them and must not use production credentials or personal financial
data.

## Data and privacy

The application may process personal and financial data when configured and
used. Local development should use synthetic data. Logs and test fixtures must
not contain credentials, raw user messages, transaction details, or other
personal data.
