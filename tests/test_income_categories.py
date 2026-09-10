"""Unit tests for user income category normalization."""

import pytest

from src.income_categories import DEFAULT_INCOME_CATEGORIES, normalize_income_category_name


pytestmark = pytest.mark.unit


def test_normalize_income_category_aliases_and_fallback() -> None:
    """Legacy names resolve to the supported canonical category."""
    assert normalize_income_category_name("Bonus") == "Bonus lavorativo"
    assert normalize_income_category_name("stipendio") == "Stipendio"
    assert normalize_income_category_name(None) == "Altra entrata"


def test_default_categories_are_the_user_bootstrap_set() -> None:
    """New users get the approved, stable set of income categories."""
    assert DEFAULT_INCOME_CATEGORIES == (
        "Stipendio", "Bonus lavorativo", "Rimborso", "Regalo",
        "Cashback", "Dividendi", "Interessi", "Altra entrata",
    )


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_normalize_income_category_empty_values_use_fallback(value: str) -> None:
    """Blank legacy values never leave an income without a category."""
    assert normalize_income_category_name(value) == "Altra entrata"
