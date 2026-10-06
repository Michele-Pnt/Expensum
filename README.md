# Expensum

Expensum is an open-source personal finance assistant. It combines a Telegram
bot, a Flask backend, and a Next.js web app to record and review expenses,
income, budgets, and reports. Financial data can be stored through the
PostgreSQL or Notion adapters. AI and messaging integrations are optional and
require accounts and credentials from their providers.

> This project is under active development. Review generated classifications,
> summaries, and forecasts before relying on them. Expensum is not financial,
> tax, or investment advice.

## Features

- Record transactions through the web app or Telegram, including text and
  receipt images.
- Review analytics, budgets, recurring items, and forecasts.
- Use PostgreSQL or connect a Notion workspace for financial storage.
- Configure supported AI providers, or develop and test without live provider
  credentials.

## Requirements

- Python 3.12
- Node.js 20.9 or later and npm
- PostgreSQL for a local database, or a configured Notion workspace
- Provider accounts and credentials for integrations you enable

## Local setup

```bash
git clone https://github.com/Michele-Pnt/Finance-Agents.git
cd Finance-Agents

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock

cp .env.example .env
```

Edit `.env` for the integrations you intend to run. Keep credentials in this
local file or a secrets manager; never commit them. The example file documents
the supported settings. Do not reuse production credentials for development.

Start the frontend in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The frontend runs at <http://localhost:3000>. Backend entry points and optional
local PostgreSQL helpers are documented in [Development](docs/development.md).

## Tests and checks

The test suite mocks external services and does not require live Telegram,
Notion, or AI credentials:

```bash
pytest -m unit
pytest
```

Frontend checks:

```bash
cd frontend
npm test
npm run lint
npm run typecheck
npm run build
```

PostgreSQL-specific tests are optional and documented in
[Development](docs/development.md).

## Project documentation

- [Development setup](docs/development.md)
- [Architecture overview](docs/public-architecture.md)
- [Documentation index](docs/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

The project code is available under the [MIT License](LICENSE). Third-party
packages and assets retain their own licenses; see their respective projects
for details.
