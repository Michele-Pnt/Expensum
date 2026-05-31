"""Cifra i notion_access_token esistenti in chiaro con Fernet (AES-128-CBC + HMAC).

Questa è una data migration: non cambia lo schema (la colonna resta VARCHAR),
ma re-encripta ogni token esistente usando la chiave derivata da FLASK_SECRET_KEY.
Il TypeDecorator EncryptedString in user_store.py gestirà trasparentemente
encrypt/decrypt da questo momento in poi.

ATTENZIONE: eseguire SOLO dopo aver impostato FLASK_SECRET_KEY nell'ambiente.
Se la variabile non è impostata, la migrazione è no-op (nessun token da cifrare
potrà essere decifrato in seguito).

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-05-24 00:01:00.000000
"""
from typing import Sequence, Union

import base64
import hashlib
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _make_fernet():
    """Crea istanza Fernet dalla stessa derivazione usata in user_store._get_fernet()."""
    from cryptography.fernet import Fernet
    secret = os.environ.get("FLASK_SECRET_KEY", "")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def upgrade() -> None:
    secret = os.environ.get("FLASK_SECRET_KEY", "")
    if not secret:
        # Senza chiave non possiamo cifrare — i token restano in chiaro.
        # Il TypeDecorator ha un fallback che li legge as-is fino alla prossima migrazione.
        return

    fernet = _make_fernet()
    conn = op.get_bind()

    rows = conn.execute(
        text("SELECT chat_id, notion_access_token FROM users WHERE notion_access_token IS NOT NULL")
    ).fetchall()

    for chat_id, token in rows:
        # Salta i token già cifrati (iniziano con "gAAAAA", prefisso Fernet base64)
        if token.startswith("gAAAAA"):
            continue
        encrypted = fernet.encrypt(token.encode()).decode()
        conn.execute(
            text("UPDATE users SET notion_access_token = :enc WHERE chat_id = :cid"),
            {"enc": encrypted, "cid": chat_id},
        )


def downgrade() -> None:
    secret = os.environ.get("FLASK_SECRET_KEY", "")
    if not secret:
        return

    fernet = _make_fernet()
    conn = op.get_bind()

    rows = conn.execute(
        text("SELECT chat_id, notion_access_token FROM users WHERE notion_access_token IS NOT NULL")
    ).fetchall()

    for chat_id, token in rows:
        if not token.startswith("gAAAAA"):
            continue
        try:
            plaintext = fernet.decrypt(token.encode()).decode()
            conn.execute(
                text("UPDATE users SET notion_access_token = :plain WHERE chat_id = :cid"),
                {"plain": plaintext, "cid": chat_id},
            )
        except Exception:
            pass
