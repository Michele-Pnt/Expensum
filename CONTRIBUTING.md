# Contributing

Thanks for considering a contribution. Issues and pull requests should focus
on one change and include enough context to review it.

## Before you start

- Search existing issues and pull requests to avoid duplicating work.
- For a substantial change, open an issue first to discuss the approach.
- Never include real financial records, personal data, credentials, or
  production configuration in code, tests, screenshots, or logs.

## Development

Follow the setup in [README.md](README.md) and
[docs/development.md](docs/development.md). Add or update tests for behavior
changes. Mock external APIs and services; tests must not contact production
systems or require real credentials.

Before opening a pull request, run the relevant checks:

```bash
pytest
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```

Use English for identifiers and documentation, add type hints to Python
functions, and keep changes focused. Database schema changes need an Alembic
migration. Do not add a new external service or dependency without explaining
why it is needed and how it affects configuration and privacy.

## Pull requests

Describe the problem, the change, and how you verified it. Link related issues,
call out migration or configuration changes, and include screenshots only
when they help explain a user-visible change. Keep unrelated formatting or
generated files out of the pull request.
