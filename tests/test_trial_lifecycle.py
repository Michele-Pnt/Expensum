import logging
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from src import trial_lifecycle

pytestmark = pytest.mark.unit


def test_compute_days_since_trial_start():
    started = datetime(2026, 1, 1)
    assert trial_lifecycle.compute_days_since_trial_start(started, date(2026, 1, 8)) == 7
    assert trial_lifecycle.compute_days_since_trial_start(started, date(2026, 1, 1)) == 0


def test_steps_pending_exact_day_no_history():
    assert trial_lifecycle.steps_pending(7, set()) == ["d7"]


def test_steps_pending_already_sent():
    assert trial_lifecycle.steps_pending(7, {"d7"}) == []


def test_steps_pending_backfills_missed_days():
    """Se il job non gira per giorni, recupera tutti gli step arretrati mancanti."""
    assert trial_lifecycle.steps_pending(30, set()) == ["d7", "d14", "d25", "d29"]


def test_steps_pending_day29_exact():
    assert trial_lifecycle.steps_pending(29, {"d7", "d14", "d25"}) == ["d29"]


def test_steps_pending_before_first_threshold():
    assert trial_lifecycle.steps_pending(3, set()) == []


def test_count_user_expenses_since_signup():
    storage = MagicMock()
    storage.fetch_all_transactions.return_value = [{"amount": 10}, {"amount": 20}]
    trial_started_at = datetime(2026, 1, 1)

    count = trial_lifecycle.count_user_expenses_since_signup(storage, trial_started_at)

    assert count == 2
    storage.fetch_all_transactions.assert_called_once_with(
        start_date=trial_started_at.date(), end_date=date.today()
    )


def test_build_drip_message_substitutes_placeholders():
    text = trial_lifecycle.build_drip_message("d7", "telegram", {"expense_count": 5})
    assert "contate 5" in text


def test_build_drip_message_missing_placeholder_logs_warning_and_returns_template(caplog):
    lifecycle_logger = trial_lifecycle.logger
    was_disabled = lifecycle_logger.disabled
    lifecycle_logger.disabled = False
    try:
        with caplog.at_level(logging.WARNING, logger=lifecycle_logger.name):
            text = trial_lifecycle.build_drip_message("d7", "telegram", {})
    finally:
        lifecycle_logger.disabled = was_disabled

    assert "{expense_count}" in text
    assert any(r.message == "Placeholder mancante nel template drip" for r in caplog.records)


def test_build_drip_message_email_channel_uses_html_template():
    text = trial_lifecycle.build_drip_message(
        "d29", "email",
        {"discount_code": "PRO30", "piani_url": "https://example.com/login?next=/abbonamenti", "name": " Michele"},
    )
    assert "PRO30" in text
    assert "https://example.com/login?next=/abbonamenti" in text
    assert "Ciao Michele," in text
