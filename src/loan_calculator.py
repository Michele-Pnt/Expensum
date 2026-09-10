"""
src/loan_calculator.py — Motore di calcolo puro per mutui/finanziamenti.

Nessuna dipendenza da storage/rete: solo matematica finanziaria, testabile in
isolamento. Il chiamante (src/storage/postgres_storage.py, bot.py) è responsabile
di leggere/scrivere lo stato del `Loan`.

Convenzioni fisse per la v1 (vedi design approvato, nessuna resa configurabile
dall'utente perché cambierebbe "cosa significa un numero", non solo dove/quanto):
- Ammortamento francese a rata costante (capitale + interessi costanti per periodo,
  a parità di tasso).
- Capitalizzazione composta, tasso nominale annuo (`tan_annual`) convertito in tasso
  mensile con `tan_annual / 100 / 12` (Exact/365 non serve: la rata è mensile fissa).
- Per il tasso variabile "classico" (rata varia, durata fissa): a ogni revisione si
  ricalcola la rata su `residual_balance`/`tan_annual` correnti e sulla durata
  residua, mai sulla durata originale.

`tan_annual`/`taeg`/`spread`/`euribor` sono percentuali (es. Decimal("3.25") per 3,25%),
mai frazioni.
"""

from datetime import date
from decimal import Decimal


PAYMENT_CADENCE_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semiannual": 6,
    "yearly": 12,
}


def cadence_months(payment_cadence: str = "monthly") -> int:
    """Restituisce ogni quanti mesi viene pagata una rata."""
    try:
        return PAYMENT_CADENCE_MONTHS[payment_cadence]
    except KeyError as exc:
        raise ValueError("payment_cadence non valido") from exc


def _round_money(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def calculate_installment(
    principal: Decimal, tan_annual: Decimal, duration_months: int,
    payment_cadence: str = "monthly",
) -> Decimal:
    """Rata costante di ammortamento francese.

    Se `tan_annual` è zero (caso limite, prestito a tasso zero) la rata è la
    semplice divisione del capitale sui mesi, senza componente interessi.
    """
    if duration_months <= 0:
        raise ValueError("duration_months deve essere positivo")

    principal_f = float(principal)
    cadence = cadence_months(payment_cadence)
    periods = (duration_months + cadence - 1) // cadence
    periodic_rate = float(tan_annual) / 100 * cadence / 12

    if periodic_rate == 0:
        return _round_money(principal_f / periods)

    installment = principal_f * periodic_rate / (1 - (1 + periodic_rate) ** -periods)
    return _round_money(installment)


def build_amortization_schedule(
    principal: Decimal, tan_annual: Decimal, duration_months: int,
    payment_cadence: str = "monthly",
) -> list[dict]:
    """Piano di ammortamento completo, un dict per rata.

    L'ultima rata assorbe l'arrotondamento residuo, così `residual_balance`
    arriva esattamente a zero invece di restare a qualche centesimo per via
    degli arrotondamenti intermedi.
    """
    cadence = cadence_months(payment_cadence)
    periods = (duration_months + cadence - 1) // cadence
    installment = calculate_installment(principal, tan_annual, duration_months, payment_cadence)
    periodic_rate = float(tan_annual) / 100 * cadence / 12
    residual = float(principal)
    schedule: list[dict] = []

    for period in range(1, periods + 1):
        interest = residual * periodic_rate
        if period == periods:
            principal_component = residual
            payment = principal_component + interest
        else:
            principal_component = float(installment) - interest
            payment = float(installment)
        residual = max(residual - principal_component, 0.0)
        schedule.append({
            "period": period,
            "installment": _round_money(payment),
            "interest": _round_money(interest),
            "principal": _round_money(principal_component),
            "residual_balance": _round_money(residual),
        })

    return schedule


def split_current_payment(
    residual_balance: Decimal, tan_annual: Decimal, installment: Decimal
) -> tuple[Decimal, Decimal]:
    """Scompone la rata corrente in (quota_capitale, quota_interessi).

    Usata per il tasso variabile, dove non conviene ricostruire l'intero piano
    a ogni revisione: basta il saldo residuo, il TAN corrente e la rata corrente.
    Solo la quota interessi è una spesa reale (vedi CLAUDE.md/design: il
    capitale è riduzione di debito, non spesa).
    """
    monthly_rate = float(tan_annual) / 100 / 12
    interest = float(residual_balance) * monthly_rate
    principal_component = float(installment) - interest
    return _round_money(principal_component), _round_money(interest)


def calculate_taeg(
    principal: Decimal,
    tan_annual: Decimal,
    duration_months: int,
    upfront_fee: Decimal = Decimal("0"),
    monthly_fee: Decimal = Decimal("0"),
    payment_cadence: str = "monthly",
) -> Decimal:
    """TAEG (IRR mensile annualizzato) su capitale netto erogato e rate totali.

    `upfront_fee` (es. istruttoria) riduce il capitale netto ricevuto al tempo 0;
    `monthly_fee` (es. spese incasso rata) si somma a ogni rata. Indicatore di
    confronto: non guida mai il calcolo della rata (quello resta sempre il TAN).
    Risolto per bisezione sul tasso mensile — robusto per i range di tassi reali
    (0-30% annuo), non serve un solver più sofisticato per questo caso d'uso.

    Anche senza costi accessori il risultato è leggermente superiore al TAN
    nominale: è l'equivalente annuo effettivo del tasso mensile composto
    (es. TAN 3% -> TAEG ≈ 3,04%), non un errore di arrotondamento.
    """
    cadence = cadence_months(payment_cadence)
    periods = (duration_months + cadence - 1) // cadence
    installment = float(calculate_installment(principal, tan_annual, duration_months, payment_cadence))
    periodic_payment = installment + float(monthly_fee) * cadence
    net_disbursement = float(principal) - float(upfront_fee)
    n = periods

    def npv(rate: float) -> float:
        if rate <= -1:
            return float("inf")
        return sum(periodic_payment / (1 + rate) ** (t * cadence) for t in range(1, n + 1)) - net_disbursement

    lo, hi = 0.0, 1.0
    while npv(hi) > 0 and hi < 100:
        hi *= 2

    for _ in range(100):
        mid = (lo + hi) / 2
        val = npv(mid)
        if abs(val) < 1e-9:
            lo = hi = mid
            break
        if val > 0:
            lo = mid
        else:
            hi = mid

    monthly_irr = (lo + hi) / 2
    taeg = ((1 + monthly_irr) ** 12 - 1) * 100
    return Decimal(str(round(taeg, 4)))


def _add_months(value: date, months: int) -> date:
    """Somma mesi mantenendo il giorno se presente nel mese di destinazione."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    # I riferimenti del mutuo sono normalmente il primo del mese; il minimo
    # evita comunque date non valide per input amministrativi diversi.
    days_in_month = (date(year + (month == 12), month % 12 + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(value.day, days_in_month))


def summarize_remaining_loan(
    residual_balance: Decimal,
    tan_annual: Decimal,
    remaining_months: int,
    reference_date: date,
) -> dict:
    """Riassume il futuro di un mutuo dal capitale residuo e dal TAN corrente.

    Per i variabili è una proiezione al tasso di oggi: non pretende di prevedere
    l'Euribor. ``reference_date`` è l'ultima rata contabilizzata, oppure la data
    di erogazione prima del primo addebito.
    """
    schedule = build_amortization_schedule(residual_balance, tan_annual, remaining_months)
    next_payment = schedule[0]
    return {
        "remaining_months": remaining_months,
        "estimated_end_date": _add_months(reference_date, remaining_months),
        "remaining_interest": sum(item["interest"] for item in schedule),
        "next_principal": next_payment["principal"],
        "next_interest": next_payment["interest"],
    }
