"""Canonical names and compatibility normalization for income categories."""

DEFAULT_INCOME_CATEGORIES: tuple[str, ...] = (
    "Stipendio",
    "Bonus lavorativo",
    "Rimborso",
    "Regalo",
    "Cashback",
    "Dividendi",
    "Interessi",
    "Altra entrata",
)

# Descrizioni comportamentali statiche per DEFAULT_INCOME_CATEGORIES, usate come
# `description_summary` nel prompt del parser LLM (vedi
# `ExpenseParser(income_category_descriptions=...)`) — stesso principio di
# `CATEGORY_DESCRIPTIONS` in workspace_bootstrapper.py per le categorie di spesa.
# L'utente può comunque riscriverle in webapp in qualsiasi momento.
INCOME_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Stipendio": "Lo stipendio mensile da lavoro dipendente",
    "Bonus lavorativo": "Premi, bonus o tredicesima/quattordicesima da lavoro",
    "Rimborso": "Rimborsi ricevuti (spese anticipate, assicurazioni, tasse)",
    "Regalo": "Denaro ricevuto in regalo da altre persone",
    "Cashback": "Cashback o rimborsi da acquisti con carta o app",
    "Dividendi": "Dividendi da azioni o partecipazioni societarie",
    "Interessi": "Interessi maturati su conti, depositi o investimenti",
    "Altra entrata": "Entrate generiche che non rientrano in nessun'altra categoria",
}

LEGACY_INCOME_CATEGORY_ALIASES: dict[str, str] = {
    "bonus": "Bonus lavorativo",
    "bonus aziendale": "Bonus lavorativo",
    "stipendio": "Stipendio",
    "salary": "Stipendio",
    "rimborso": "Rimborso",
    "regalo": "Regalo",
    "cashback": "Cashback",
    "dividendi": "Dividendi",
    "interessi": "Interessi",
    "altra entrata": "Altra entrata",
}


def normalize_income_category_name(value: str | None) -> str:
    """Return a deterministic canonical name for a legacy income category.

    Unknown non-empty values are deliberately preserved: the migration turns them
    into a user-owned custom category rather than losing their historical meaning.
    """
    if value is None or not value.strip():
        return "Altra entrata"
    cleaned = value.strip()
    canonical = LEGACY_INCOME_CATEGORY_ALIASES.get(cleaned.casefold())
    if canonical is not None:
        return canonical
    for name in DEFAULT_INCOME_CATEGORIES:
        if name.casefold() == cleaned.casefold():
            return name
    return cleaned
