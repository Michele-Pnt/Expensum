"""Progressive onboarding persistence contracts."""

import pytest


pytestmark = pytest.mark.integration


def test_goals_replace_atomically_and_keep_priority(mock_db_session):
    """A second save replaces the ordered goal selection in one transaction."""
    mock_db_session.add_user(chat_id="onboarding-user", storage_backend="postgres")
    mock_db_session.save_onboarding_profile(
        "onboarding-user",
        [
            {"code": "budget", "priority_order": 1},
            {"code": "emergency_fund", "priority_order": 2},
        ],
        {"has_job": True, "household_type": "single"},
    )
    mock_db_session.save_onboarding_profile(
        "onboarding-user", [{"code": "increase_savings", "priority_order": 1}]
    )

    assert mock_db_session.get_profile_goals("onboarding-user") == ["increase_savings"]
