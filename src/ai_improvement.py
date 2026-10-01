"""Consent-bound structured AI quality samples with bounded retention."""

import json
from datetime import datetime, timedelta

from src.consent_service import ConsentService
from src.storage.models import AiImprovementSample
from src.user_store import ConsentEvent


ALLOWED_FIELDS = frozenset({
    "transaction_type", "category_id", "category_name", "merchant",
    "amount", "currency", "transaction_date",
})
CONSENT_BY_INPUT = {
    "text": "structured_text_usage",
    "voice": "structured_voice_usage",
    "ocr": "ocr_text_usage",
}


def _structured_fields(value: dict) -> dict:
    """Extract an allowlisted structured subset without arbitrary parser payloads."""
    return {key: value[key] for key in ALLOWED_FIELDS if key in value}


def capture_quality_sample(
    store,
    user_id: str,
    input_method: str,
    proposed: dict,
    final: dict,
    model_metadata: dict,
    ocr_text: str | None = None,
) -> bool:
    """Persist a structured sample only when current consent allows its source."""
    source_consent = CONSENT_BY_INPUT.get(input_method)
    if source_consent is None:
        return False
    consents = ConsentService(store).current(user_id)
    if not consents.get("algorithm_improvement") or not consents.get(source_consent):
        return False
    proposed_fields = _structured_fields(proposed)
    final_fields = _structured_fields(final)
    changed_fields = sorted(
        key for key in set(proposed_fields) | set(final_fields)
        if proposed_fields.get(key) != final_fields.get(key)
    )
    with store.Session() as session:
        event = session.query(ConsentEvent).filter(
            ConsentEvent.user_id == str(user_id),
            ConsentEvent.consent_type == source_consent,
            ConsentEvent.granted.is_(True),
        ).order_by(ConsentEvent.created_at.desc(), ConsentEvent.id.desc()).first()
        if event is None:
            return False
        session.add(AiImprovementSample(
            user_id=str(user_id), input_method=input_method,
            proposed_fields_json=proposed_fields, final_fields_json=final_fields,
            changed_fields_json=changed_fields,
            model_provider=str(model_metadata.get("provider", "unknown"))[:64],
            model_name=str(model_metadata.get("model", "unknown"))[:128],
            consent_event_id=event.id,
            ocr_text_encrypted=ocr_text if input_method == "ocr" else None,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=90),
        ))
        session.commit()
    return True


def delete_user_quality_samples(store, user_id: str) -> int:
    """Delete all identifiable quality samples for a user after withdrawal."""
    with store.Session() as session:
        deleted = session.query(AiImprovementSample).filter(
            AiImprovementSample.user_id == str(user_id)
        ).delete(synchronize_session=False)
        session.commit()
        return deleted


def cleanup_expired_ai_samples(store, days: int = 90, now: datetime | None = None) -> int:
    """Delete samples past their explicit expiry or the retention horizon."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=days)
    with store.Session() as session:
        deleted = session.query(AiImprovementSample).filter(
            (AiImprovementSample.expires_at <= now)
            | (AiImprovementSample.created_at <= cutoff)
        ).delete(synchronize_session=False)
        session.commit()
        return deleted
