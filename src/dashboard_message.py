"""
src/dashboard_message.py — Costruisce il messaggio di dashboard per Telegram.

Genera un testo Markdown formattato con:
  - Saldi di tutti i conti attivi
  - Abbonamenti attivi con prossima rata stimata
  - (Premium) Spese per categoria del mese corrente
  - (Premium) Media storica per categoria
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from src.billing_utils import get_next_billing_date

logger = logging.getLogger("financial_agent.dashboard")


def _estimate_next_billing_str(last_billed_str: str | None, sub_type: str | None) -> str:
    """Ritorna la stringa formattata della prossima data di fatturazione."""
    next_date = get_next_billing_date(last_billed_str, sub_type)
    if not next_date:
        return "N/D"
    return next_date.strftime("%d/%m/%Y")


def build_dashboard_text(
    accounts: list[dict],
    subscriptions: list[dict],
    categories_spending: list[dict] | None = None,
    is_premium: bool = False,
    user_plan: dict | None = None,
) -> str:
    """Costruisce il testo Markdown della dashboard Telegram.

    Args:
        accounts: Lista di dict con almeno {name, current_balance o balance}.
        subscriptions: Lista di dict con almeno {name, amount, last_billed, sub_type}.
        categories_spending: Lista di dict {name, spent_this_month, average}.
                            Solo per utenti Premium.
        is_premium: Se True, mostra le sezioni avanzate (categorie + medie).

    Returns:
        Stringa Markdown-safe per Telegram.
    """
    today = date.today()
    lines = []

    # Intestazione
    lines.append(f"🐷 *Moneo Dashboard*")
    lines.append(f"📅 {today.strftime('%d/%m/%Y')}")
    lines.append("")

    # ---------------------------------------------------------------
    # SEZIONE 1: Conti attivi
    # ---------------------------------------------------------------
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🏦 *I Tuoi Conti*")
    lines.append("")

    total_balance = 0.0
    if accounts:
        for acc in accounts:
            name = acc.get("name", "Sconosciuto")
            # Supporta sia 'current_balance' (Notion) che 'balance' (Postgres)
            balance = float(acc.get("current_balance") or acc.get("balance") or 0)
            total_balance += balance
            emoji = "💳" if balance >= 0 else "🔴"
            lines.append(f"  {emoji} {name}: *€{balance:,.2f}*")
        lines.append("")
        lines.append(f"  💰 Totale: *€{total_balance:,.2f}*")
    else:
        lines.append("  _Nessun conto configurato_")

    lines.append("")

    # ---------------------------------------------------------------
    # SEZIONE 2: Abbonamenti attivi
    # ---------------------------------------------------------------
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🔁 *Abbonamenti Attivi*")
    lines.append("")

    total_subs = 0.0
    if subscriptions:
        for sub in subscriptions:
            name = sub.get("name", "Sconosciuto")
            amount = sub.get("amount")
            sub_type = sub.get("sub_type")
            last_billed = sub.get("last_billed")
            next_billing = _estimate_next_billing_str(last_billed, sub_type)

            if amount is not None:
                amount = float(amount)
                total_subs += amount
                lines.append(f"  📌 {name}: *€{amount:,.2f}*")
            else:
                lines.append(f"  📌 {name}: _importo N/D_")

            type_label = sub_type or "Mensile"
            lines.append(f"      ↳ {type_label} · Prossima: {next_billing}")
        lines.append("")
        lines.append(f"  💸 Totale abbonamenti: *€{total_subs:,.2f}/mese*")
    else:
        lines.append("  _Nessun abbonamento attivo_")

    # ---------------------------------------------------------------
    # SEZIONE 3: Spese per categoria (Premium)
    # ---------------------------------------------------------------
    if is_premium and categories_spending:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("📊 *Spese per Categoria* (mese corrente)")
        lines.append("")

        total_spent = 0.0
        for cat in categories_spending:
            cat_name = cat.get("name", "Sconosciuta")
            spent = float(cat.get("spent_this_month") or 0)
            average = float(cat.get("average") or 0)
            total_spent += spent

            # Indicatore trend: ↗️ sopra media, ↘️ sotto media, ➡️ in media
            if average > 0:
                ratio = spent / average
                if ratio > 1.15:
                    trend = "🔺"
                elif ratio < 0.85:
                    trend = "🔽"
                else:
                    trend = "▪️"
            else:
                trend = "▪️"

            lines.append(f"  {trend} {cat_name}: *€{spent:,.2f}*")
            if average > 0:
                lines.append(f"      ↳ Media storica: €{average:,.2f}")

        lines.append("")
        lines.append(f"  🧾 Totale mese: *€{total_spent:,.2f}*")

    if user_plan:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        plan_name = user_plan.get('plan_type', 'free').upper()
        rem = user_plan.get('tokens_remaining', 0)
        tot = user_plan.get('tokens_total', 0)
        percent = round(((tot - rem) / tot) * 100) if tot > 0 else 0
        lines.append(f"🤖 *AI Token* ({plan_name})")
        lines.append(f"  ↳ {rem:,} / {tot:,} ({percent}% usati)")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    # Footer con ultimo aggiornamento
    now = datetime.now()
    lines.append(f"🔄 Aggiornato: {now.strftime('%H:%M — %d/%m/%Y')}")

    return "\n".join(lines)
