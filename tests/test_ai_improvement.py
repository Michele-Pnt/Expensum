"""Consent-bound AI quality sample contracts."""

import json

import pytest

from src.ai_improvement import capture_quality_sample
from src.consent_service import ConsentService
from src.storage.models import AiImprovementSample


pytestmark = pytest.mark.integration

PROPOSED = {"transaction_type": "expense", "category_id": 2, "raw": "testo vietato"}
FINAL = {"transaction_type": "expense", "category_id": 3}
MODEL = {"provider": "mistral", "model": "small"}


def _service(store):
    store.add_user(chat_id="ai-user", storage_backend="postgres")
    consent = ConsentService(store)
    consent.record("ai-user", "algorithm_improvement", True, "v1", "settings")
    consent.record("ai-user", "structured_voice_usage", True, "v1", "settings")
    consent.record("ai-user", "structured_text_usage", True, "v1", "settings")
    consent.record("ai-user", "ocr_text_usage", True, "v1", "settings")


def test_voice_sample_stores_structured_diff_without_transcript(mock_db_session):
    """Voice samples never persist the transcript or arbitrary fields."""
    _service(mock_db_session)
    assert capture_quality_sample(
        mock_db_session, "ai-user", "voice", PROPOSED, FINAL, MODEL,
        ocr_text="testo vietato",
    ) is True
    with mock_db_session.Session() as session:
        row = session.query(AiImprovementSample).one()
        assert row.ocr_text_encrypted is None
        assert "testo vietato" not in json.dumps(row.proposed_fields_json)


def test_ocr_requires_parent_and_ocr_consent(mock_db_session):
    """OCR text requires both the parent and source-specific consent."""
    mock_db_session.add_user(chat_id="ocr-user", storage_backend="postgres")
    ConsentService(mock_db_session).record(
        "ocr-user", "algorithm_improvement", True, "v1", "settings"
    )
    assert capture_quality_sample(
        mock_db_session, "ocr-user", "ocr", PROPOSED, FINAL, MODEL, "contenuto"
    ) is False


def test_withdrawal_deletes_existing_sample_and_blocks_late_capture(mock_db_session):
    """Withdrawal removes old samples and immediately blocks new capture."""
    _service(mock_db_session)
    assert capture_quality_sample(
        mock_db_session, "ai-user", "text", PROPOSED, FINAL, MODEL
    ) is True
    ConsentService(mock_db_session).record(
        "ai-user", "algorithm_improvement", False, "v1", "settings"
    )
    assert capture_quality_sample(
        mock_db_session, "ai-user", "text", PROPOSED, FINAL, MODEL
    ) is False
    with mock_db_session.Session() as session:
        assert session.query(AiImprovementSample).filter_by(user_id="ai-user").count() == 0
