"""
tests/test_weekly_plan.py — Unit test per i componenti del piano settimanale.

Copre:
- WeeklyPatternAnalyzer: stats per categoria sulle 8 settimane
- MonthlyResidualCalc: residuo mensile e settimane rimaste
- CategoryMomentum: rilevamento trend ultimi 4w vs media 8w
- WeeklyBudgetCalc: limite reale e soft cap per categoria
- SubscriptionScheduler: abbonamenti in scadenza questa settimana
- WeeklyPlanData.to_prompt_text: serializzazione per il prompt AI
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock

from src.data_processor import (
    WeeklyPatternAnalyzer,
    MonthlyResidualCalc,
    CategoryMomentum,
    WeeklyBudgetCalc,
    WeeklyCategoryStats,
)
from src.report_builder import SubscriptionScheduler, WeeklyPlanBuilder, WeeklyPlanData

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monday_n_weeks_ago(n: int) -> date:
    """Ritorna il lunedì di N settimane fa."""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(weeks=n)


def _make_transactions(category: str, amounts_per_week: list[float]) -> list[dict]:
    """Crea transazioni fake: una per settimana, il martedì di ciascuna settimana."""
    txs = []
    for i, amt in enumerate(reversed(amounts_per_week)):
        week_monday = _monday_n_weeks_ago(i + 1)
        txs.append({
            "date": week_monday + timedelta(days=1),  # martedì
            "category": category,
            "name": f"{category} settimana {i+1}",
            "amount": amt,
        })
    return txs


def _make_stats(mean: float, weekly_amounts: list[float] | None = None) -> WeeklyCategoryStats:
    """Crea un WeeklyCategoryStats con mean e weekly_amounts controllati."""
    s = WeeklyCategoryStats("Test")
    s.weekly_amounts = weekly_amounts or [mean] * 8
    s.mean = mean
    return s


# ---------------------------------------------------------------------------
# WeeklyPatternAnalyzer
# ---------------------------------------------------------------------------

class TestWeeklyPatternAnalyzer:

    def test_computes_mean_for_category(self):
        amounts = [50.0, 60.0, 40.0, 55.0, 45.0, 70.0, 50.0, 60.0]
        txs = _make_transactions("Alimentari", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)

        assert "Alimentari" in stats
        s = stats["Alimentari"]
        assert abs(s.mean - sum(amounts) / len(amounts)) < 0.01

    def test_filters_fake_categories(self):
        txs = _make_transactions("Movimenti", [100.0] * 8)
        txs += _make_transactions("Alimentari", [50.0] * 8)
        stats = WeeklyPatternAnalyzer().compute(txs)

        assert "Movimenti" not in stats
        assert "Alimentari" in stats

    def test_p75_higher_than_mean_for_bimodal_data(self):
        amounts = [10.0, 10.0, 10.0, 10.0, 100.0, 100.0, 100.0, 100.0]
        txs = _make_transactions("Ristoranti", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)

        s = stats["Ristoranti"]
        assert s.p75 > s.mean

    def test_std_dev_is_zero_for_constant_amounts(self):
        amounts = [50.0] * 8
        txs = _make_transactions("Trasporti", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)

        assert abs(stats["Trasporti"].std_dev) < 0.01

    def test_empty_transactions_returns_empty(self):
        stats = WeeklyPatternAnalyzer().compute([])
        assert stats == {}

    def test_day_of_week_share_sums_to_one(self):
        txs = []
        for i in range(7):
            week_monday = _monday_n_weeks_ago(i + 1)
            txs.append({
                "date": week_monday + timedelta(days=i % 7),
                "category": "Carburante",
                "name": "Carburante",
                "amount": 30.0,
            })
        stats = WeeklyPatternAnalyzer().compute(txs)
        if "Carburante" in stats:
            total_share = sum(stats["Carburante"].day_of_week_share.values())
            assert abs(total_share - 1.0) < 0.01


# ---------------------------------------------------------------------------
# MonthlyResidualCalc
# ---------------------------------------------------------------------------

class TestMonthlyResidualCalc:

    def test_weeks_remaining_early_in_month(self):
        ref = date(2026, 5, 2)
        _, _, weeks = MonthlyResidualCalc().compute([], [], ref)
        assert weeks > 4.0

    def test_weeks_remaining_end_of_month(self):
        ref = date(2026, 5, 29)
        _, _, weeks = MonthlyResidualCalc().compute([], [], ref)
        assert 0.5 <= weeks < 1.0

    def test_spent_by_cat_aggregated_correctly(self):
        txs = [
            {"date": date(2026, 5, 1), "category": "Alimentari", "amount": 80.0},
            {"date": date(2026, 5, 5), "category": "Alimentari", "amount": 40.0},
            {"date": date(2026, 5, 3), "category": "Ristoranti", "amount": 60.0},
        ]
        spent, _, _ = MonthlyResidualCalc().compute(txs, [], date(2026, 5, 10))
        assert abs(spent["Alimentari"] - 120.0) < 0.01
        assert abs(spent["Ristoranti"] - 60.0) < 0.01

    def test_budget_by_cat_from_categories(self):
        cats = [
            {"name": "Alimentari", "monthly_budget": 300.0},
            {"name": "Ristoranti", "monthly_budget": None},
        ]
        _, budget, _ = MonthlyResidualCalc().compute([], cats, date(2026, 5, 10))
        assert "Alimentari" in budget
        assert "Ristoranti" not in budget

    def test_filters_fake_categories(self):
        txs = [
            {"date": date(2026, 5, 1), "category": "Movimenti", "amount": 500.0},
            {"date": date(2026, 5, 1), "category": "Alimentari", "amount": 50.0},
        ]
        spent, _, _ = MonthlyResidualCalc().compute(txs, [], date(2026, 5, 10))
        assert "Movimenti" not in spent
        assert "Alimentari" in spent


# ---------------------------------------------------------------------------
# CategoryMomentum
# ---------------------------------------------------------------------------

class TestCategoryMomentum:

    def test_improvement_when_last_4w_much_lower(self):
        amounts = [100.0, 100.0, 100.0, 100.0, 60.0, 60.0, 60.0, 60.0]
        txs = _make_transactions("Ristoranti", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)
        mom = CategoryMomentum().compute(stats)
        assert mom.get("Ristoranti") == "in miglioramento"

    def test_worsening_when_last_4w_much_higher(self):
        amounts = [50.0, 50.0, 50.0, 50.0, 80.0, 80.0, 80.0, 80.0]
        txs = _make_transactions("Acquisti", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)
        mom = CategoryMomentum().compute(stats)
        assert mom.get("Acquisti") == "in peggioramento"

    def test_stable_when_consistent(self):
        amounts = [50.0, 52.0, 48.0, 51.0, 49.0, 50.0, 53.0, 51.0]
        txs = _make_transactions("Trasporti", amounts)
        stats = WeeklyPatternAnalyzer().compute(txs)
        mom = CategoryMomentum().compute(stats)
        assert mom.get("Trasporti") == "stabile"


# ---------------------------------------------------------------------------
# WeeklyBudgetCalc
# ---------------------------------------------------------------------------

class TestWeeklyBudgetCalc:

    # Data fissa: 14 feb 2026 (mese da 28 giorni, esattamente a metà)
    # → days_elapsed=14, days_in_month=28, projected = spent * 2
    REF = date(2026, 2, 14)

    def test_limite_reale_no_softcap(self):
        # budget 300, speso 150, 2 settimane rimaste → limite_reale = 75, soft_cap = None
        # proiezione = 150 * 2 = 300 → non supera il budget → "ok"
        budget = {"Alimentari": 300.0}
        spent = {"Alimentari": 150.0}
        stats = {"Alimentari": _make_stats(mean=50.0)}  # costante → delta = 0

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        assert "Alimentari" in results
        r = results["Alimentari"]
        assert abs(r.limite_reale - 75.0) < 0.01
        assert r.soft_cap is None
        assert r.status == "ok"
        assert abs(r.residuo - 150.0) < 0.01
        assert r.overrun == 0.0

    def test_soft_cap_applied_when_trend_worsening(self):
        # media 8w = 50, ultime 4w = 65 → delta = +30% → soft_cap attivo (riduzione 25%)
        # il soft_cap è solo per il limite visivo; lo status dipende dalla proiezione mensile
        # proiezione = 80 * 2 = 160 < 200 → "ok"
        budget = {"Ristoranti": 200.0}
        spent = {"Ristoranti": 80.0}  # residuo 120, limite_reale = 60 (2 settimane)
        weekly_amounts = [50.0, 50.0, 50.0, 50.0, 65.0, 65.0, 65.0, 65.0]
        stats = {"Ristoranti": _make_stats(mean=sum(weekly_amounts) / 8, weekly_amounts=weekly_amounts)}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        r = results["Ristoranti"]
        assert r.soft_cap is not None
        assert r.soft_cap < r.limite_reale
        assert r.soft_cap_reason != ""
        # proiezione non supera il budget → status ok (soft_cap non guida più lo status)
        assert r.status == "ok"

    def test_attenzione_when_projection_exceeds_budget(self):
        # proiezione = 120 * 2 = 240 > 200 → "attenzione"
        budget = {"Ristoranti": 200.0}
        spent = {"Ristoranti": 120.0}
        stats = {"Ristoranti": _make_stats(mean=50.0)}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        r = results["Ristoranti"]
        assert r.status == "attenzione"
        assert r.overrun == 0.0  # non ancora sforato

    def test_soft_cap_capped_at_25_percent(self):
        # delta = +80% → riduzione deve essere capped al 25%
        budget = {"Svago": 400.0}
        spent = {"Svago": 0.0}
        weekly_amounts = [20.0, 20.0, 20.0, 20.0, 80.0, 80.0, 80.0, 80.0]
        mean = sum(weekly_amounts) / 8
        stats = {"Svago": _make_stats(mean=mean, weekly_amounts=weekly_amounts)}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        r = results["Svago"]
        assert r.soft_cap is not None
        # riduzione massima = 25% → soft_cap >= limite_reale * 0.75
        assert r.soft_cap >= r.limite_reale * 0.74
        assert abs(r.reduction_pct - 25.0) < 0.1

    def test_sforato_when_budget_exceeded(self):
        # speso 250 > budget 200 → overrun=50, limite_reale=0, status="sforato"
        budget = {"Viaggi": 200.0}
        spent = {"Viaggi": 250.0}
        stats = {"Viaggi": _make_stats(mean=50.0)}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        r = results["Viaggi"]
        assert r.status == "sforato"
        assert r.limite_reale == 0.0
        assert abs(r.overrun - 50.0) < 0.01
        assert r.residuo == 0.0

    def test_no_soft_cap_when_stable_momentum(self):
        # delta < 10% → no soft cap
        # proiezione = 50 * 2 = 100 < 150 → "ok"
        budget = {"Trasporti": 150.0}
        spent = {"Trasporti": 50.0}
        # media = 40, ultime 4w = 43 → delta = 7.5% < 10%
        weekly_amounts = [40.0, 40.0, 40.0, 40.0, 43.0, 43.0, 43.0, 43.0]
        stats = {"Trasporti": _make_stats(
            mean=sum(weekly_amounts) / 8, weekly_amounts=weekly_amounts
        )}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        r = results["Trasporti"]
        assert r.soft_cap is None
        assert r.status == "ok"

    def test_categoria_senza_budget_non_nel_dict(self):
        # categoria in pattern_stats ma non in budget_by_cat → non inclusa nel risultato
        budget = {"Alimentari": 300.0}
        spent = {"Alimentari": 100.0, "Svago": 50.0}
        stats = {
            "Alimentari": _make_stats(mean=50.0),
            "Svago": _make_stats(mean=30.0),
        }

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats=stats, reference_date=self.REF
        )

        assert "Alimentari" in results
        assert "Svago" not in results

    def test_no_pattern_stats_no_soft_cap(self):
        # categoria senza storico pattern → soft_cap = None, ma limite_reale calcolato
        budget = {"Nuovo": 100.0}
        spent = {"Nuovo": 20.0}

        results = WeeklyBudgetCalc().compute(
            budget, spent, weeks_remaining=2.0, pattern_stats={}, reference_date=self.REF
        )

        r = results["Nuovo"]
        assert r.soft_cap is None
        assert abs(r.limite_reale - 40.0) < 0.01


# ---------------------------------------------------------------------------
# SubscriptionScheduler
# ---------------------------------------------------------------------------

class TestSubscriptionScheduler:

    def test_monthly_sub_due_this_week(self):
        ref = date(2026, 5, 14)
        sub = {
            "name": "Netflix",
            "amount": 15.99,
            "last_billed": date(2026, 4, 15).isoformat(),
            "sub_type": "mensile",
        }
        result = SubscriptionScheduler().due_this_week([sub], ref)
        assert len(result) == 1
        assert result[0]["due_date"] == date(2026, 5, 15)

    def test_monthly_sub_not_due_this_week(self):
        ref = date(2026, 5, 10)
        sub = {
            "name": "Spotify",
            "amount": 9.99,
            "last_billed": date(2026, 4, 28).isoformat(),
            "sub_type": "mensile",
        }
        result = SubscriptionScheduler().due_this_week([sub], ref)
        assert len(result) == 0

    def test_weekly_sub_always_due_in_7_days(self):
        ref = date(2026, 5, 14)
        sub = {
            "name": "Palestra",
            "amount": 10.0,
            "last_billed": date(2026, 5, 7).isoformat(),
            "sub_type": "settimanale",
        }
        result = SubscriptionScheduler().due_this_week([sub], ref)
        assert len(result) == 1

    def test_no_last_billed_skipped(self):
        ref = date(2026, 5, 14)
        sub = {"name": "Unknown", "amount": 5.0, "last_billed": None, "sub_type": "mensile"}
        result = SubscriptionScheduler().due_this_week([sub], ref)
        assert len(result) == 0

    def test_multiple_subs_filters_correctly(self):
        ref = date(2026, 5, 14)
        subs = [
            {"name": "Netflix", "amount": 15.99, "last_billed": date(2026, 4, 15).isoformat(), "sub_type": "mensile"},
            {"name": "Spotify", "amount": 9.99, "last_billed": date(2026, 4, 28).isoformat(), "sub_type": "mensile"},
        ]
        result = SubscriptionScheduler().due_this_week(subs, ref)
        assert len(result) == 1
        assert result[0]["name"] == "Netflix"


# ---------------------------------------------------------------------------
# WeeklyPlanBuilder — test con mock FinancialStorage
# ---------------------------------------------------------------------------

class TestWeeklyPlanBuilder:

    def _make_storage(self):
        storage = MagicMock()
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        history_txs = []
        for i in range(1, 9):
            monday = week_start - timedelta(weeks=i)
            history_txs.append({
                "date": monday + timedelta(days=1),
                "category": "Alimentari",
                "amount": 60.0 + i * 2,
                "name": "Spesa",
            })

        storage.fetch_all_transactions.return_value = history_txs
        storage.fetch_income.return_value = [{"date": today, "amount": 1500.0, "name": "Stipendio"}]
        storage.fetch_accounts.return_value = [{"name": "Conto principale", "current_balance": 3000.0}]
        storage.fetch_subscriptions.return_value = []
        storage.get_categories.return_value = [
            {"name": "Alimentari", "monthly_budget": 300.0, "average": 65.0}
        ]
        return storage

    def test_build_returns_weekly_plan_data(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        assert isinstance(data, WeeklyPlanData)
        assert data.total_accounts == 3000.0
        assert "Alimentari" in data.budget_results

    def test_build_populates_spent_last_week_by_cat(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        assert "Alimentari" in data.spent_last_week_by_cat
        assert abs(data.spent_last_week_by_cat["Alimentari"] - 62.0) < 0.01

    def test_build_populates_budget_results(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        r = data.budget_results["Alimentari"]
        assert r.budget_monthly == 300.0
        assert r.limite_reale >= 0.0
        assert r.status in ("ok", "attenzione", "sforato")

    @staticmethod
    def _section(content, heading: str):
        """Cerca la sezione con l'heading dato dentro `content['sections']`."""
        for section in content["sections"]:
            if section["heading"] == heading:
                return section
        raise AssertionError(f"Sezione '{heading}' non trovata: {[s['heading'] for s in content['sections']]}")

    def test_fallback_text_generated(self):
        # Ex `build_fallback_text` (Markdown): oggi il contenuto è un ReportContent
        # strutturato (vedi src/report_schema.py). Verifica lo stesso comportamento
        # di business (titolo del piano settimanale + KPI presenti) sulla struttura
        # dict invece che su substring di testo libero.
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        content = WeeklyPlanBuilder().build_content(data)
        assert content["title"].startswith("Piano Settimanale")
        kpi_labels = {k["label"] for k in content["kpis"]}
        assert "Saldo conti" in kpi_labels
        assert "Entrate mese" in kpi_labels
        assert "Settimane rimaste" in kpi_labels

    def test_fallback_text_no_code_block_table(self):
        # Con il vecchio fallback Markdown la tabella budget era un blocco di
        # codice ASCII con substring "```"; con ReportContent la tabella è una
        # struttura tipizzata (type == "table"), quindi il concetto di "niente
        # code block" non si applica più a livello di stringa. Verifichiamo
        # invece che la sezione budget sia effettivamente strutturata come
        # tabella (non testo libero che potrebbe reintrodurre ASCII art).
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        content = WeeklyPlanBuilder().build_content(data)
        budget_section = self._section(content, "Budget per categoria")
        assert budget_section["type"] == "table"

    def test_fallback_text_no_budget_category_shown(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        data.no_budget_cats["Svago"] = 25.0
        content = WeeklyPlanBuilder().build_content(data)
        section = self._section(content, "Categorie senza budget (stima storica)")
        assert any("Svago" in item for item in section["items"])

    def test_fallback_text_abbonamenti_shown(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        content = WeeklyPlanBuilder().build_content(data)
        self._section(content, "Abbonamenti in uscita questa settimana")

    def test_fallback_text_no_budget_message_when_empty(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        data.budget_results = {}
        content = WeeklyPlanBuilder().build_content(data)
        section = self._section(content, "Budget per categoria")
        assert section["rows"] == []
        assert "budget impostato" in section["empty_message"]

    def test_to_prompt_text_contains_key_sections(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        prompt = data.to_prompt_text()
        assert "PIANO SETTIMANALE" in prompt
        assert "BUDGET MENSILE PER CATEGORIA" in prompt
        assert "Alimentari" in prompt
        assert "limite_reale" in prompt

    def test_to_prompt_text_contains_ai_instruction(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        prompt = data.to_prompt_text()
        assert "limite reale" in prompt
        assert "limite consigliato" in prompt
        assert "IMPORTANTE" in prompt

    def test_to_prompt_text_zero_spend_tag(self):
        storage = self._make_storage()
        data = WeeklyPlanBuilder().build(storage)
        # Categoria con spesa zero nella settimana scorsa
        from src.data_processor import CategoryBudgetResult
        r = CategoryBudgetResult()
        r.budget_monthly = 200.0
        r.spent_month = 0.0
        r.residuo = 200.0
        r.limite_reale = 50.0
        r.status = "ok"
        data.budget_results["Viaggi"] = r
        data.spent_last_week_by_cat["Viaggi"] = 0.0
        prompt = data.to_prompt_text()
        assert "spesa=0: non mostrare avvisi negativi" in prompt
