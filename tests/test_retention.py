"""Retention tests for consent-bound AI samples."""

from datetime import datetime, timedelta

import pytest

from src.ai_improvement import capture_quality_sample
from src.consent_service import ConsentService
from src.storage.models import AiImprovementSample


pytestmark = pytest.mark.integration


def test_cleanup_expired_ai_samples(mock_db_session):
    """Expired structured samples are removed by the retention repository."""
    mock_db_session.add_user(chat_id="retention-ai", storage_backend="postgres")
    consent = ConsentService(mock_db_session)
    consent.record("retention-ai", "algorithm_improvement", True, "v1", "settings")
    consent.record("retention-ai", "structured_text_usage", True, "v1", "settings")
    capture_quality_sample(
        mock_db_session, "retention-ai", "text", {"amount": 1}, {"amount": 1},
        {"provider": "mistral", "model": "small"},
    )
    with mock_db_session.Session() as session:
        row = session.query(AiImprovementSample).one()
        row.created_at = datetime.utcnow() - timedelta(days=91)
        session.commit()

    assert mock_db_session.cleanup_expired_ai_samples() == 1
