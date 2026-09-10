"""Risoluzione agnostica dello storage dei riferimenti testuali ai conti."""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence


def resolve_account_hint(
    hint: str | None,
    accounts: Sequence[Mapping[str, object]],
    *,
    cutoff: float = 0.6,
) -> Mapping[str, object] | None:
    """Restituisce il conto corrispondente a un hint libero oppure ``None``.

    Il confronto privilegia l'uguaglianza normalizzata e ricorre poi a un fuzzy
    match deterministico sui soli nomi validi. Il contratto usa ``Mapping`` per
    restare indipendente dall'implementazione dello storage finanziario.
    """
    if not isinstance(hint, str):
        return None

    normalized_hint = hint.strip().casefold()
    if not normalized_hint:
        return None

    normalized_accounts: list[tuple[str, Mapping[str, object]]] = []
    for account in accounts:
        name = account.get("name")
        if not isinstance(name, str):
            continue
        normalized_name = name.strip().casefold()
        if not normalized_name:
            continue
        if normalized_name == normalized_hint:
            return account
        normalized_accounts.append((normalized_name, account))

    names = [name for name, _ in normalized_accounts]
    matches = difflib.get_close_matches(normalized_hint, names, n=1, cutoff=cutoff)
    if not matches:
        return None
    return next(account for name, account in normalized_accounts if name == matches[0])
