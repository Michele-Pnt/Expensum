"""Sintesi LLM one-shot della descrizione di una categoria (spesa o entrata).

Modulo leaf puro (nessuna dipendenza da Flask/app.py/blueprint): usato sia dalle
categorie di spesa (`app.py`, in corso di migrazione a `space_routes.py`) sia
dalle categorie di entrata (`blueprints/income_categories_routes.py`).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _synthesize_category_description(raw_description: str) -> str | None:
    """Sintesi LLM one-shot della descrizione categoria (vedi
    `MistralClient.synthesize_category_description`) — chiamata solo quando la
    descrizione cambia, non ad ogni parsing spesa."""
    from src.mistral_client import MistralClient
    try:
        return MistralClient().synthesize_category_description(raw_description)
    except Exception as exc:
        logger.warning(
            "category_description_synthesis_unavailable",
            extra={"domain": "financial", "event": "category_description_synthesis_unavailable",
                   "meta": {"error_type": type(exc).__name__}},
        )
        return None
