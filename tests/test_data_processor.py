"""
tests/test_data_processor.py — Unit test per DataProcessor.

Copre:
- Aggregazione mensile con pandas
- Calcolo trend e delta percentuale
- Rilevamento anomalie sopra soglia
- Serializzazione in testo per il prompt Gemini
"""

import pytest
from datetime import date
from src.data_processor import DataProcessor, MonthlySummary


# ---------------------------------------------------------------------------
# Fixture: dati di test comuni
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_transactions():
    """Transazioni su 3 mesi con anomalia in Ristoranti a Febbraio."""
    return [
        # Dicembre 2025
        {"date": date(2025, 12, 1),  "category": "Affitto",     "name": "Affitto",   "amount": 650.0},
        {"date": date(2025, 12, 5),  "category": "Abbonamenti",  "name": "Netflix",   "amount": 13.99},
        {"date": date(2025, 12, 10), "category": "Supermercato", "name": "Spesa",     "amount": 120.0},
        {"date": date(2025, 12, 20), "category": "Ristoranti",   "name": "Cena",      "amount": 40.0},
        # Gennaio 2026
        {"date": date(2026, 1, 1),   "category": "Affitto",     "name": "Affitto",   "amount": 650.0},
        {"date": date(2026, 1, 5),   "category": "Abbonamenti",  "name": "Netflix",   "amount": 13.99},
        {"date": date(2026, 1, 10),  "category": "Supermercato", "name": "Spesa",     "amount": 110.0},
        {"date": date(2026, 1, 20),  "category": "Ristoranti",   "name": "Pranzo",   "amount": 35.0},
        # Febbraio 2026 (anomalia Ristoranti: 120 vs media ~37.5)
        {"date": date(2026, 2, 1),   "category": "Affitto",     "name": "Affitto",   "amount": 650.0},
        {"date": date(2026, 2, 5),   "category": "Abbonamenti",  "name": "Netflix",   "amount": 13.99},
        {"date": date(2026, 2, 10),  "category": "Supermercato", "name": "Spesa",     "amount": 95.0},
        {"date": date(2026, 2, 15),  "category": "Ristoranti",   "name": "Cena",      "amount": 60.0},
        {"date": date(2026, 2, 20),  "category": "Ristoranti",   "name": "Compleanno","amount": 60.0},
    ]


# ---------------------------------------------------------------------------
# Test: aggregazione mensile
# ---------------------------------------------------------------------------

class TestAggregation:

    def test_process_returns_correct_month(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        assert report.current_month is not None
        assert report.current_month.year == 2026
        assert report.current_month.month == 2

    def test_total_is_sum_of_amounts(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        feb_transactions = [t for t in sample_transactions if t["date"].month == 2]
        expected_total = sum(t["amount"] for t in feb_transactions)
        assert abs(report.current_month.total - expected_total) < 0.01

    def test_categories_present(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        cats = report.current_month.by_category
        assert "Affitto" in cats
        assert "Abbonamenti" in cats
        assert "Supermercato" in cats
        assert "Ristoranti" in cats

    def test_history_excludes_current_month(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        for hist_month in report.history:
            assert not (hist_month.year == 2026 and hist_month.month == 2)

    def test_history_count(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        # 2 mesi storici (Gen, Dic)
        assert len(report.history) == 2

    def test_top_categories_ordering(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        top = report.current_month.top_categories(5)
        amounts = [amt for _, amt in top]
        assert amounts == sorted(amounts, reverse=True)


# ---------------------------------------------------------------------------
# Test: trend analysis
# ---------------------------------------------------------------------------

class TestTrend:

    def test_historical_avg_computed(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        assert report.historical_avg > 0

    def test_delta_pct_sign(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        # Febbraio ha più ristoranti, quindi delta può variare
        # ma il calcolo deve essere coerente con il segno
        expected_sign = report.current_month.total > report.historical_avg
        if expected_sign:
            assert report.delta_pct > 0
        else:
            assert report.delta_pct <= 0

    def test_trend_direction_values(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        assert report.trend_direction in ("crescita", "contrazione", "stabile")

    def test_empty_transactions_returns_empty_report(self):
        dp = DataProcessor()
        report = dp.process([], 2026, 2)
        assert report.current_month is None or report.current_month.total == 0.0


# ---------------------------------------------------------------------------
# Test: rilevamento anomalie
# ---------------------------------------------------------------------------

class TestAnomalies:

    def test_anomaly_detected_for_high_restaurants(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        # Ristoranti: Feb=120, storia=[40,35] → media=37.5 → delta=+220% >> 25%
        anomaly_cats = [a["category"] for a in report.anomalies]
        assert "Ristoranti" in anomaly_cats

    def test_stable_category_not_anomaly(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        # Affitto è identico ogni mese (650) → non anomalia
        anomaly_cats = [a["category"] for a in report.anomalies]
        assert "Affitto" not in anomaly_cats

    def test_anomaly_delta_pct_matches_threshold(self, sample_transactions):
        dp = DataProcessor()
        dp.threshold_pct = 200  # Soglia molto alta
        report = dp.process(sample_transactions, 2026, 2)
        for a in report.anomalies:
            assert abs(a["delta_pct"]) >= 200

    def test_anomaly_direction_field(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        for a in report.anomalies:
            assert a["direction"] in ("aumento", "riduzione")
            if a["delta_pct"] > 0:
                assert a["direction"] == "aumento"
            else:
                assert a["direction"] == "riduzione"


# ---------------------------------------------------------------------------
# Test: serializzazione prompt
# ---------------------------------------------------------------------------

class TestPromptText:

    def test_prompt_text_contains_key_sections(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        text = dp.to_prompt_text(report)
        assert "MESE ANALIZZATO" in text
        assert "SPESE PER CATEGORIA" in text
        assert "STORICO" in text
        assert "ANOMALIE" in text

    def test_prompt_text_contains_total(self, sample_transactions):
        dp = DataProcessor()
        report = dp.process(sample_transactions, 2026, 2)
        text = dp.to_prompt_text(report)
        total_str = f"€{report.current_month.total:.2f}"
        assert total_str in text
