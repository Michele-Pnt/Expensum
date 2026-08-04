"""
tests/test_wealth.py — Test puri per src/wealth.py.

Copre la regressione che ha motivato il modulo: /api/analytics/capital-trend
mostrava un capitale negativo mentre "Il mio spazio" mostrava conti positivi,
perche' le spese senza conto venivano accumulate in un bucket partito da zero.

Nessun DB: la storage e' un doppio scritto a mano, come in
tests/test_savings_goals_service.py.
"""
import pytest
from datetime import date

from src.wealth import build_wealth_series

pytestmark = pytest.mark.unit


class FakeStorage:
    """Doppio minimale di FinancialStorage: risponde solo a cio' che serve al test."""

    def __init__(self, accounts=None, incomes=None, expenses=None, transfers=None):
        self._accounts = accounts or []
        self._incomes = incomes or []
        self._expenses = expenses or []
        self._transfers = transfers or []

    def fetch_accounts(self):
        return self._accounts

    def fetch_income(self, start_date, end_date):
        return [i for i in self._incomes if start_date <= i["date"] <= end_date]

    def fetch_all_transactions(self, start_date, end_date):
        return [e for e in self._expenses if start_date <= e["date"] <= end_date]

    def fetch_transfers(self, start_date, end_date):
        return [t for t in self._transfers if start_date <= t["date"] <= end_date]


def _account(acc_id, name="Conto", opening=0.0):
    return {"id": acc_id, "name": name, "opening_balance": opening}


def _current_balance(storage):
    """Replica di PostgresStorage._compute_balance: la definizione di riferimento."""
    total = 0.0
    for acc in storage.fetch_accounts():
        balance = float(acc.get("opening_balance") or 0.0)
        for inc in storage._incomes:
            if inc.get("account_id") == acc["id"]:
                balance += inc["amount"]
        for exp in storage._expenses:
            if exp.get("account_id") == acc["id"]:
                balance -= exp["amount"]
        for tr in storage._transfers:
            if tr.get("to_account_id") == acc["id"]:
                balance += tr["amount"]
            if tr.get("from_account_id") == acc["id"]:
                balance -= tr["amount"]
        total += balance
    return round(total, 2)


class TestOrphanTransactions:
    """Il bug originale: spese senza conto che affondavano il capitale."""

    def test_expenses_without_account_do_not_sink_capital(self):
        storage = FakeStorage(
            accounts=[_account(1, "Principale", opening=1000.0)],
            expenses=[
                {"date": date(2026, 5, 10), "amount": 50.0, "account_id": 1},
                # Spese registrate da chat senza indicare il conto.
                {"date": date(2026, 5, 11), "amount": 300.0, "account_id": None},
                {"date": date(2026, 6, 12), "amount": 400.0, "account_id": None},
            ],
        )
        series = build_wealth_series(storage, date(2026, 6, 30))

        assert [p.total for p in series.points] == [950.0, 950.0]
        assert all(p.total > 0 for p in series.points)
        # Le spese orfane non spariscono: vengono esposte a parte.
        assert series.unassigned_expenses == 700.0

    def test_expenses_on_deleted_account_are_excluded(self):
        """Un conto cancellato lascia spese con account_id ormai inesistente."""
        storage = FakeStorage(
            accounts=[_account(1, "Principale", opening=500.0)],
            expenses=[
                {"date": date(2026, 5, 10), "amount": 100.0, "account_id": 1},
                {"date": date(2026, 5, 11), "amount": 900.0, "account_id": 99},
            ],
        )
        series = build_wealth_series(storage, date(2026, 5, 31))

        assert series.points[-1].total == 400.0
        assert series.unassigned_expenses == 900.0

    def test_last_point_always_matches_sum_of_account_balances(self):
        """L'invariante che il bug violava: analytics e "Il mio spazio" concordano."""
        storage = FakeStorage(
            accounts=[_account(1, "Conto", opening=2000.0), _account(2, "Risparmi", opening=500.0)],
            incomes=[{"date": date(2026, 4, 1), "amount": 1800.0, "account_id": 1}],
            expenses=[
                {"date": date(2026, 4, 15), "amount": 600.0, "account_id": 1},
                {"date": date(2026, 5, 15), "amount": 250.0, "account_id": None},
            ],
            transfers=[{
                "date": date(2026, 5, 2), "amount": 300.0,
                "from_account_id": 1, "to_account_id": 2,
            }],
        )
        series = build_wealth_series(storage, date(2026, 5, 31))

        assert series.points[-1].total == _current_balance(storage)


class TestTransfers:
    def test_transfer_between_own_accounts_is_neutral_on_total(self):
        storage = FakeStorage(
            accounts=[_account(1, "A", opening=1000.0), _account(2, "B", opening=0.0)],
            transfers=[{
                "date": date(2026, 5, 3), "amount": 400.0,
                "from_account_id": 1, "to_account_id": 2,
            }],
        )
        series = build_wealth_series(storage, date(2026, 5, 31))

        assert series.points[-1].total == 1000.0
        assert series.points[-1].by_account == {1: 600.0, 2: 400.0}

    def test_transfer_moves_balance_on_single_account_series(self):
        """Il difetto secondario: le linee per-conto ignoravano i trasferimenti."""
        storage = FakeStorage(
            accounts=[_account(1, "A", opening=1000.0), _account(2, "B", opening=0.0)],
            transfers=[{
                "date": date(2026, 5, 3), "amount": 400.0,
                "from_account_id": 1, "to_account_id": 2,
            }],
        )
        only_source = build_wealth_series(storage, date(2026, 5, 31), account_id=1)
        assert only_source.points[-1].total == 600.0


class TestSeriesShape:
    def test_balance_is_cumulative_across_months(self):
        storage = FakeStorage(
            accounts=[_account(1, "Conto", opening=100.0)],
            incomes=[
                {"date": date(2026, 3, 1), "amount": 50.0, "account_id": 1},
                {"date": date(2026, 5, 1), "amount": 20.0, "account_id": 1},
            ],
        )
        series = build_wealth_series(storage, date(2026, 5, 31))

        # Aprile non ha attivita' ma compare comunque, col saldo di marzo.
        assert [(p.year, p.month, p.total) for p in series.points] == [
            (2026, 3, 150.0), (2026, 4, 150.0), (2026, 5, 170.0),
        ]

    def test_since_hides_earlier_months_but_keeps_their_effect(self):
        storage = FakeStorage(
            accounts=[_account(1, "Conto", opening=0.0)],
            incomes=[
                {"date": date(2026, 1, 5), "amount": 1000.0, "account_id": 1},
                {"date": date(2026, 5, 5), "amount": 100.0, "account_id": 1},
            ],
        )
        series = build_wealth_series(storage, date(2026, 5, 31), since=date(2026, 4, 1))

        assert [(p.year, p.month) for p in series.points] == [(2026, 4), (2026, 5)]
        # Il saldo parte da 1000: i mesi nascosti sono calcolati, non ignorati.
        assert series.points[0].total == 1000.0
        assert series.points[-1].total == 1100.0

    def test_no_accounts_returns_empty_series(self):
        assert build_wealth_series(FakeStorage(), date(2026, 5, 31)).points == []

    def test_account_without_activity_reports_opening_balance(self):
        storage = FakeStorage(accounts=[_account(1, "Conto", opening=750.0)])
        series = build_wealth_series(storage, date(2026, 5, 31), since=date(2026, 5, 1))

        assert series.points[-1].total == 750.0
