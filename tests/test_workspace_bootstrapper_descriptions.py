"""
tests/test_workspace_bootstrapper_descriptions.py — Verifica che il bootstrap
(onboarding) passi le descrizioni statiche (CATEGORY_DESCRIPTIONS) a create_category,
senza bisogno di alcuna chiamata LLM per le categorie di default/lifestyle note in
anticipo (vedi src/workspace_bootstrapper.py).
"""

import pytest
from unittest.mock import MagicMock

from src.storage.base import FinancialStorage
from src.workspace_bootstrapper import (
    CATEGORY_DESCRIPTIONS,
    DEFAULT_CATEGORIES,
    bootstrap_lifestyle_categories,
    bootstrap_workspace,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def empty_storage():
    storage = MagicMock(spec=FinancialStorage)
    storage.get_category_names.return_value = []
    storage.fetch_accounts.return_value = []
    storage.create_category.side_effect = lambda name, **kwargs: {"id": 1, "name": name}
    return storage


class TestBootstrapWorkspaceDescriptions:
    def test_passes_known_description_for_default_categories(self, empty_storage):
        bootstrap_workspace(empty_storage)

        calls_by_name = {c.args[0]: c.kwargs for c in empty_storage.create_category.call_args_list}
        assert calls_by_name["Affitto"]["description_summary"] == CATEGORY_DESCRIPTIONS["Affitto"]
        assert calls_by_name["Supermercato"]["description_summary"] == CATEGORY_DESCRIPTIONS["Supermercato"]

    def test_every_default_category_has_a_description(self):
        """Nessuna categoria di default deve restare silenziosamente senza descrizione."""
        missing = [c for c in DEFAULT_CATEGORIES if c not in CATEGORY_DESCRIPTIONS]
        assert missing == []


class TestBootstrapLifestyleCategoriesDescriptions:
    def test_passes_known_description_for_hobby_categories(self, empty_storage):
        bootstrap_lifestyle_categories(empty_storage, ["Palestra", "Integratori"])

        calls_by_name = {c.args[0]: c.kwargs for c in empty_storage.create_category.call_args_list}
        assert calls_by_name["Palestra"]["description_summary"] == CATEGORY_DESCRIPTIONS["Palestra"]
        assert calls_by_name["Integratori"]["description_summary"] == CATEGORY_DESCRIPTIONS["Integratori"]

    def test_unknown_category_gets_none_description_without_error(self, empty_storage):
        """Un nome non presente in CATEGORY_DESCRIPTIONS non deve far fallire il bootstrap."""
        bootstrap_lifestyle_categories(empty_storage, ["Categoria Inventata Xyz"])

        empty_storage.create_category.assert_called_once_with(
            "Categoria Inventata Xyz", description_summary=None,
        )
