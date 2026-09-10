"""Regression tests for owner-only PostgreSQL Alembic migrations."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


REPOSITORY_ROOT = Path(__file__).parents[1]


def test_alembic_rejects_postgres_runtime_url_without_owner_url() -> None:
    """A PostgreSQL runtime credential can never be used for DDL migrations."""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+psycopg://expensum_app:runtime-password@localhost/expensum"
    )
    environment.pop("MIGRATION_DATABASE_URL", None)
    environment["PYTHON_DOTENV_DISABLED"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(REPOSITORY_ROOT / "alembic.ini"),
            "current",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "MIGRATION_DATABASE_URL is required for PostgreSQL migrations" in (
        result.stdout + result.stderr
    )
