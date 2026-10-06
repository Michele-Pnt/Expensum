# Python tests

The default suite uses mocks for external services and local SQLite fixtures. It does not
require live Telegram, Notion, or AI credentials.

```bash
pytest -m unit
pytest
pytest --cov=src --cov-report=term-missing
```

PostgreSQL-specific tests use the optional local database described in
[the development guide](../docs/development.md).
