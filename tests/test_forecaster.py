"""
tests/test_forecaster.py — Unit test per il motore predittivo Forecaster.
"""

import pytest
from datetime import date
from src.data_processor import DataProcessor, MonthlySummary
from src.forecaster import Forecaster, ForecastResult


@pytest.fixture
def stable_history_transactions():
    """3 mesi di dati stabili: affitto fisso + spese variabili."""
    txs = []
    for year, month in [(2025, 11), (2025, 12), (2026, 1)]:
        txs += [
            {"date": date(year, month, 1),  "category": "Affitto",     "name": "Affitto",  "amount": 650.0},
            {"date": date(year, month, 5),  "category": "Abbonamenti",  "name": "Netflix",  "amount": 13.99},
            {"date": date(year, month, 10), "category": "Supermercato",  "name": "Spesa",   "amount": 100.0 + (month * 2)},
            {"date": date(year, month, 20), "category": "Ristoranti",   "name": "Cena",     "amount": 40.0 + month},
        ]
    # Mese corrente (Febbraio 2026)
    txs += [
        {"date": date(2026, 2, 1),  "category": "Affitto",     "name": "Affitto",  "amount": 650.0},
        {"date": date(2026, 2, 5),  "category": "Abbonamenti",  "name": "Netflix",  "amount": 13.99},
        {"date": date(2026, 2, 10), "category": "Supermercato",  "name": "Spesa",   "amount": 110.0},
        {"date": date(2026, 2, 20), "category": "Ristoranti",   "name": "Cena",     "amount": 44.0},
    ]
    return txs


class TestForecaster:

    def test_forecast_result_has_correct_month_label(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        result = f.predict(report, 3, 2026)
        # month_name uses the system locale; check year and month number instead
        assert "2026" in result.target_month_label
        assert "3" in result.target_month_label or "March" in result.target_month_label or "Marzo" in result.target_month_label

    def test_fixed_expenses_detected(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        result = f.predict(report, 3, 2026)
        # Affitto e Netflix dovrebbero essere identificati come fissi
        fixed_cats = {item["category"] for item in result.fixed_items}
        assert "Affitto" in fixed_cats

    def test_base_forecast_positive(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        result = f.predict(report, 3, 2026)
        assert result.base_forecast > 0

    def test_range_ordering(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        result = f.predict(report, 3, 2026)
        assert result.optimistic_forecast <= result.base_forecast <= result.pessimistic_forecast

    def test_seasonality_applied(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        # Agosto ha stagionalità 1.20, Marzo 1.0
        result_march = f.predict(report, 3, 2026)
        result_august = f.predict(report, 8, 2026)
        assert result_august.base_forecast > result_march.base_forecast

    def test_empty_report_returns_zero_forecast(self):
        from src.data_processor import TrendReport
        empty_report = TrendReport()
        f = Forecaster()
        result = f.predict(empty_report, 3, 2026)
        assert result.base_forecast == 0.0

    def test_prompt_text_contains_key_info(self, stable_history_transactions):
        dp = DataProcessor()
        report = dp.process(stable_history_transactions, 2026, 2)
        f = Forecaster()
        result = f.predict(report, 3, 2026)
        text = result.to_prompt_text()
        assert "PREVISIONE" in text
        assert "ottimistica" in text.lower() or "OTTIMISTICA" in text
        assert "pessimistica" in text.lower() or "PESSIMISTICA" in text
