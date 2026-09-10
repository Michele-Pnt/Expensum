"""Test unitari per la risoluzione canonica degli hint dei conti."""

import pytest


pytestmark = pytest.mark.unit


def test_resolve_account_hint_prefers_normalized_exact_match() -> None:
    """Un match esatto ignora maiuscole e spazi periferici."""
    from src.application.account_matching import resolve_account_hint

    accounts = (
        {"id": 1, "name": "Conto Corrente"},
        {"id": 2, "name": "Risparmio"},
    )

    assert resolve_account_hint("  risparmio ", accounts) == accounts[1]


def test_resolve_account_hint_uses_configurable_fuzzy_cutoff() -> None:
    """Il fuzzy match resta disponibile e la soglia è parte del contratto pubblico."""
    from src.application.account_matching import resolve_account_hint

    accounts = ({"id": 2, "name": "Risparmio"},)

    assert resolve_account_hint("risparmi", accounts) == accounts[0]
    assert resolve_account_hint("risparmi", accounts, cutoff=0.95) is None
