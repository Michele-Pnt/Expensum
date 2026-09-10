"""
src/report_schema.py — Schema condiviso per il contenuto strutturato dei report
(settimanale e mensile) mostrati nella webapp.

Sostituisce il vecchio formato Markdown "per Telegram" salvato in
`saved_reports.text_content`: da qui in avanti quel campo contiene JSON
serializzato secondo `ReportContent`, così il frontend può impaginare il
report con componenti tipizzati invece di euristiche su testo libero
(allineamento a spazi, regex su asterischi, ecc.).

`SCHEMA_VERSION` è la chiave che distingue i record nuovi (JSON strutturato)
da quelli storici già salvati come Markdown grezzo prima di questa modifica:
il frontend prova un `JSON.parse` e verifica `schema_version` prima di usare
i renderer nuovi, altrimenti ricade sul renderer legacy per compatibilità
con i link condivisi già esistenti (non esiste retention/cleanup su
`saved_reports`, quindi righe vecchie possono essere aperte a tempo
indeterminato).
"""

import json
from typing import Literal, TypedDict

SCHEMA_VERSION = 1

Tone = Literal["neutral", "positive", "negative", "warning"]


class KpiItem(TypedDict):
    """Una cifra chiave in evidenza (es. 'Spesa totale: €1.234,56')."""

    label: str
    value: str
    tone: Tone


class TableColumn(TypedDict):
    key: str
    label: str
    align: Literal["left", "right"]


class TableRow(TypedDict):
    cells: dict[str, str]
    tone: Tone | None


class TableSection(TypedDict):
    type: Literal["table"]
    heading: str
    columns: list[TableColumn]
    rows: list[TableRow]
    empty_message: str | None


class NarrativeSection(TypedDict):
    type: Literal["narrative"]
    heading: str
    paragraphs: list[str]


class ListSection(TypedDict):
    type: Literal["list"]
    heading: str
    items: list[str]
    empty_message: str | None


Section = TableSection | NarrativeSection | ListSection


class ReportContent(TypedDict):
    schema_version: int
    title: str
    kpis: list[KpiItem]
    sections: list[Section]
    # Indice (in `sections`) da cui il piano Free sfoca il contenuto.
    # None = report sempre interamente visibile (nessun blocco Premium).
    locked_from_section: int | None
    footer_note: str | None
    # Link referral personale (solo report mensile "pesante"), reso come vero
    # link cliccabile in webapp invece che pastato dentro al testo.
    referral_url: str | None


def validated_str_list(value: object, max_items: int, max_len: int = 400) -> list[str] | None:
    """Valida una lista di stringhe arrivata da un JSON generato dall'AI (confine
    esterno non fidato): tronca lunghezza/quantità, scarta elementi non stringa
    o vuoti. Ritorna None se il risultato finale è vuoto/non valido, così il
    chiamante può ricadere sul contenuto deterministico invece di mostrare una
    sezione vuota generata "a caso" dal modello.
    """
    if not isinstance(value, list) or not value:
        return None
    out = [" ".join(v.split()) for v in value if isinstance(v, str) and v.strip()]
    out = [s for s in out if s]
    if not out:
        return None
    return [s[:max_len] for s in out[:max_items]]


def kpi(label: str, value: str, tone: Tone = "neutral") -> KpiItem:
    """Costruisce una cifra chiave (`KpiItem`) già formattata per la visualizzazione."""
    return {"label": label, "value": value, "tone": tone}


def table_section(
    heading: str,
    columns: list[TableColumn],
    rows: list[TableRow],
    empty_message: str | None = None,
) -> TableSection:
    """Costruisce una sezione tabellare (`TableSection`).

    `empty_message` è mostrato al posto della tabella quando `rows` è vuota.
    """
    return {
        "type": "table",
        "heading": heading,
        "columns": columns,
        "rows": rows,
        "empty_message": empty_message,
    }


def narrative_section(heading: str, paragraphs: list[str]) -> NarrativeSection:
    """Costruisce una sezione di prosa (`NarrativeSection`), scartando paragrafi vuoti."""
    non_empty = [p for p in paragraphs if p]
    return {"type": "narrative", "heading": heading, "paragraphs": non_empty}


def list_section(
    heading: str, items: list[str], empty_message: str | None = None
) -> ListSection:
    """Costruisce una sezione a elenco (`ListSection`).

    `empty_message` è mostrato al posto della lista quando `items` è vuota.
    """
    return {"type": "list", "heading": heading, "items": items, "empty_message": empty_message}


def new_report_content(
    title: str,
    kpis: list[KpiItem],
    sections: list[Section],
    locked_from_section: int | None = None,
    footer_note: str | None = None,
    referral_url: str | None = None,
) -> ReportContent:
    """Assembla un `ReportContent` valido (schema_version corrente) a partire dai suoi campi."""
    return {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "kpis": kpis,
        "sections": sections,
        "locked_from_section": locked_from_section,
        "footer_note": footer_note,
        "referral_url": referral_url,
    }


def render_plain_text(content: ReportContent) -> str:
    """Rende il contenuto strutturato come testo semplice, senza alcuna sintassi
    Markdown, per i canali che non possono mostrare la webapp (fallback Telegram
    quando il salvataggio del report o l'invio del link falliscono).

    Deliberatamente senza `*grassetto*`/`_corsivo_`: categorie e tips possono
    contenere testo libero dell'utente o dell'AI con `*`/`_`/`` ` `` non
    bilanciati, che romperebbe il parsing entità di Telegram in ParseMode
    MARKDOWN. Chi invia questo testo a Telegram deve farlo SENZA parse_mode.
    """
    lines: list[str] = [content["title"]]

    if content["kpis"]:
        lines.append("")
        lines.append(" | ".join(f"{k['label']}: {k['value']}" for k in content["kpis"]))

    for section in content["sections"]:
        lines.append("")
        lines.append(section["heading"])
        if section["type"] == "narrative":
            for p in section["paragraphs"]:
                lines.append(p)
        elif section["type"] == "list":
            if section["items"]:
                for item in section["items"]:
                    lines.append(f"- {item}")
            elif section.get("empty_message"):
                lines.append(section["empty_message"])
        elif section["type"] == "table":
            if section["rows"]:
                for row in section["rows"]:
                    row_text = ", ".join(
                        f"{col['label']}: {row['cells'].get(col['key'], '')}"
                        for col in section["columns"]
                    )
                    lines.append(f"- {row_text}")
            elif section.get("empty_message"):
                lines.append(section["empty_message"])

    if content.get("footer_note"):
        lines.append("")
        lines.append(content["footer_note"])

    if content.get("referral_url"):
        lines.append("")
        lines.append(f"Invita un amico e sblocca ricompense: {content['referral_url']}")

    return "\n".join(lines)


def render_preview_text(text_content: str, max_len: int = 500) -> str:
    """Anteprima breve di `saved_reports.text_content` per superfici che mostrano
    solo un estratto (es. cronologia chat webapp): JSON strutturato -> testo
    semplice via `render_plain_text`, Markdown legacy -> testo grezzo invariato
    (nessuna migrazione dati: le righe storiche restano Markdown per sempre).
    """
    try:
        parsed = json.loads(text_content)
    except (ValueError, TypeError):
        parsed = None

    text = (
        render_plain_text(parsed)
        if isinstance(parsed, dict) and parsed.get("schema_version") == SCHEMA_VERSION
        else text_content
    )

    if len(text) > max_len:
        return text[:max_len] + "…"
    return text
