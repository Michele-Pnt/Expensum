from datetime import date, datetime, timedelta
from typing import Optional

def get_next_billing_date(last_billed: date | str | None, sub_type: str | None) -> Optional[date]:
    """Calcola la prossima data di fatturazione in base al tipo di abbonamento.
    
    Ritorna un oggetto datetime.date o None se input non valido.
    """
    if not last_billed:
        return None

    if isinstance(last_billed, str):
        try:
            # Supporta sia ISO che date semplici
            if "T" in last_billed:
                last_date = datetime.fromisoformat(last_billed).date()
            else:
                last_date = datetime.strptime(last_billed, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    else:
        last_date = last_billed

    sub_type_lower = (sub_type or "monthly").lower()

    if sub_type_lower in ("yearly", "annuale", "annual"):
        try:
            next_date = last_date.replace(year=last_date.year + 1)
        except ValueError: # Gestione 29 Febbraio
            next_date = last_date.replace(year=last_date.year + 1, day=28)
    elif sub_type_lower in ("weekly", "settimanale"):
        next_date = last_date + timedelta(days=7)
    elif sub_type_lower in ("bi-mensile", "bimensile", "bimestrale", "bimonthly"):
        month = last_date.month + 2
        year = last_date.year
        while month > 12:
            month -= 12
            year += 1
        day = min(last_date.day, 28)
        next_date = last_date.replace(year=year, month=month, day=day)
    elif sub_type_lower in ("trimestrale", "quarterly"):
        month = last_date.month + 3
        year = last_date.year
        while month > 12:
            month -= 12
            year += 1
        day = min(last_date.day, 28)
        next_date = last_date.replace(year=year, month=month, day=day)
    elif sub_type_lower in ("semestrale", "semi-annual", "semiannual", "biannual"):
        month = last_date.month + 6
        year = last_date.year
        while month > 12:
            month -= 12
            year += 1
        day = min(last_date.day, 28)
        next_date = last_date.replace(year=year, month=month, day=day)
    else:
        # Default: mensile
        month = last_date.month + 1
        year = last_date.year
        while month > 12:
            month -= 12
            year += 1
        day = min(last_date.day, 28)
        next_date = last_date.replace(year=year, month=month, day=day)

    return next_date
