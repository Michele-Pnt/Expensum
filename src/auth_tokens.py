"""Secure one-time token issuance and consumption for web authentication flows."""

from datetime import datetime, timedelta
import hashlib
import hmac
import os
import secrets

from sqlalchemy import update

from config import Config
from src.user_store import AuthToken


TOKEN_PURPOSES = frozenset({"email_verification", "password_reset"})


def _secret_key() -> bytes:
    """Return the configured HMAC key, with a test-only development fallback."""
    secret = os.getenv("FLASK_SECRET_KEY") or Config.FLASK_SECRET_KEY
    if not secret:
        if os.getenv("TESTING", "false").lower() == "true":
            return b"test-only-auth-token-key"
        raise RuntimeError("FLASK_SECRET_KEY is required for authentication tokens")
    return secret.encode("utf-8")


def _digest(raw_token: str) -> str:
    """Hash a raw token with HMAC-SHA256 before database persistence."""
    return hmac.new(_secret_key(), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_auth_token(store, user_id: str, purpose: str, ttl: timedelta) -> str:
    """Invalidate old tokens and persist a new high-entropy token digest."""
    with store.Session() as session:
        raw_token = _issue_auth_token_in_session(session, user_id, purpose, ttl)
        session.commit()
    return raw_token


def _issue_auth_token_in_session(session, user_id: str, purpose: str, ttl: timedelta) -> str:
    """Issue a token using a caller-owned transaction."""
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"Unsupported authentication token purpose: {purpose}")
    raw_token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    session.query(AuthToken).filter(
        AuthToken.user_id == str(user_id),
        AuthToken.purpose == purpose,
        AuthToken.used_at.is_(None),
        AuthToken.invalidated_at.is_(None),
    ).update({"invalidated_at": now}, synchronize_session=False)
    session.add(
        AuthToken(
            user_id=str(user_id),
            token_digest=_digest(raw_token),
            purpose=purpose,
            expires_at=now + ttl,
            created_at=now,
        )
    )
    return raw_token


def consume_auth_token(store, raw_token: str, purpose: str) -> str | None:
    """Atomically consume a valid token and return its user id once."""
    with store.Session() as session:
        user_id = _consume_auth_token_in_session(session, raw_token, purpose)
        if user_id is not None:
            session.commit()
        return user_id


def _consume_auth_token_in_session(session, raw_token: str, purpose: str) -> str | None:
    """Consume a token using a caller-owned transaction."""
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"Unsupported authentication token purpose: {purpose}")
    now = datetime.utcnow()
    digest = _digest(raw_token)
    token = session.query(AuthToken).filter(
        AuthToken.token_digest == digest,
        AuthToken.purpose == purpose,
        AuthToken.used_at.is_(None),
        AuthToken.invalidated_at.is_(None),
        AuthToken.expires_at > now,
    ).first()
    if token is None:
        return None
    result = session.execute(
        update(AuthToken)
        .where(
            AuthToken.id == token.id,
            AuthToken.used_at.is_(None),
            AuthToken.invalidated_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if result.rowcount != 1:
        return None
    return token.user_id
