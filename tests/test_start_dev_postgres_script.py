"""Contratti di sicurezza per il launcher locale PostgreSQL."""

from pathlib import Path


def test_start_dev_postgres_never_echoes_database_url() -> None:
    """Il launcher non deve esporre password dalla URL del database nei log."""
    script = (Path(__file__).parents[1] / "scripts" / "start_dev_postgres.sh").read_text()

    assert 'echo "[postgres]  DATABASE_URL attiva: $DATABASE_URL"' not in script
    assert 'echo "[postgres]  DATABASE_URL caricata dall\'.env.local (segreto nascosto)"' in script
