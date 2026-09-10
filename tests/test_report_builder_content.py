"""
tests/test_report_builder_content.py — Unit test per `ReportBuilder.build_content`
(report mensile "pesante"), la controparte di ReportBuilder rispetto a
WeeklyPlanBuilder/MonthlyPlanBuilder già coperti in test_weekly_plan.py e
test_monthly_plan.py.

Contesto: prima del refactor a `ReportContent` (src/report_schema.py) questo
metodo si chiamava `build_fallback_report` e restituiva una stringa Markdown;
non esisteva però nessun test dedicato (gap pre-esistente, non introdotto da
questo refactor). Qui copriamo il contratto strutturale del nuovo
`ReportContent`: KPI sempre calcolati deterministicamente, tabella categorie,
sostituzione della narrazione via `ai_narrative` senza toccare KPI/tabelle.

Nessuna chiamata reale a Mistral o storage: solo dataclass in-memory
(TrendReport, ForecastResult).
"""

import pytest

from src.data_processor import MonthlySummary, TrendReport
from src.forecaster import ForecastResult
from src.report_builder import ReportBuilder

pytestmark = pytest.mark.unit


def _make_report(total: float = 500.0, historical_avg: float = 400.0) -> TrendReport:
    cur = MonthlySummary(2026, 9)
    cur.total = total
    cur.by_category = {"Alimentari": 300.0, "Trasporti": 200.0}
    cur.by_category_average = {"Alimentari": 250.0, "Trasporti": 150.0}

    report = TrendReport()
    report.current_month = cur
    report.historical_avg = historical_avg
    report.delta_pct = (total - historical_avg) / historical_avg * 100 if historical_avg else 0.0
    report.trend_direction = "crescita" if report.delta_pct > 5 else "stabile"
    report.total_income = 1200.0
    return report


def _make_forecast() -> ForecastResult:
    forecast = ForecastResult()
    forecast.target_month_label = "Ottobre 2026"
    forecast.base_forecast = 450.0
    forecast.optimistic_forecast = 405.0
    forecast.pessimistic_forecast = 517.5
    forecast.fixed_items = []
    forecast.fixed_expenses = 0.0
    return forecast


class TestReportBuilderBuildContent:
    def test_title_and_kpis_from_real_data(self):
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast, net_savings=200.0)

        assert content["title"] == f"Riepilogo {report.current_month.label}"
        kpis = {k["label"]: k["value"] for k in content["kpis"]}
        assert kpis["Spesa totale"] == "€500.00"
        assert kpis["Entrate totali"] == "€1200.00"
        assert kpis["Risparmio mensile"] == "€200.00"

    def test_kpi_savings_tone_positive_when_net_savings_positive(self):
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast, net_savings=200.0)
        savings_kpi = next(k for k in content["kpis"] if k["label"] == "Risparmio mensile")
        assert savings_kpi["tone"] == "positive"

    def test_kpi_savings_unavailable_when_none(self):
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast, net_savings=None)
        savings_kpi = next(k for k in content["kpis"] if k["label"] == "Risparmio mensile")
        assert savings_kpi["value"] == "n/d"

    def test_category_table_reflects_real_spending(self):
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast)
        cat_section = next(s for s in content["sections"] if s["heading"] == "Spesa per categorie")
        assert cat_section["type"] == "table"
        categories = {row["cells"]["categoria"] for row in cat_section["rows"]}
        assert categories == {"Alimentari", "Trasporti"}

    def test_accounts_liquidity_section_present_only_when_accounts_given(self):
        report = _make_report()
        forecast = _make_forecast()
        accounts = [{"name": "Conto principale", "current_balance": 1000.0}]

        with_accounts = ReportBuilder.build_content(report, forecast, accounts=accounts)
        without_accounts = ReportBuilder.build_content(report, forecast, accounts=None)

        assert any(s["heading"] == "Liquidità per conto" for s in with_accounts["sections"])
        assert not any(s["heading"] == "Liquidità per conto" for s in without_accounts["sections"])

    def test_ai_narrative_replaces_default_paragraphs_and_tips_only(self):
        report = _make_report()
        forecast = _make_forecast()
        ai_narrative = {
            "trend_paragraphs": ["Paragrafo generato da Mistral."],
            "tips": ["Consiglio generato da Mistral."],
        }
        content = ReportBuilder.build_content(report, forecast, ai_narrative=ai_narrative)

        trend_section = next(s for s in content["sections"] if s["heading"] == "Analisi e Confronto Trend")
        assert trend_section["paragraphs"] == ["Paragrafo generato da Mistral."]

        tips_section = next(s for s in content["sections"] if s["heading"] == "Consigli Azionabili")
        assert tips_section["items"] == ["Consiglio generato da Mistral."]

        # KPI e tabella categorie non devono mai dipendere dall'AI.
        cat_section = next(s for s in content["sections"] if s["heading"] == "Spesa per categorie")
        categories = {row["cells"]["categoria"] for row in cat_section["rows"]}
        assert categories == {"Alimentari", "Trasporti"}

    def test_ai_narrative_invalid_falls_back_to_deterministic_content(self):
        """`ai_narrative` con liste vuote/non valide non deve produrre sezioni vuote:
        ricade sui paragrafi/tips generati deterministicamente (vedi
        `validated_str_list` in src/report_schema.py)."""
        report = _make_report()
        forecast = _make_forecast()
        content_default = ReportBuilder.build_content(report, forecast)
        content_invalid_ai = ReportBuilder.build_content(
            report, forecast, ai_narrative={"trend_paragraphs": [], "tips": None}
        )

        default_trend = next(
            s for s in content_default["sections"] if s["heading"] == "Analisi e Confronto Trend"
        )
        invalid_trend = next(
            s for s in content_invalid_ai["sections"] if s["heading"] == "Analisi e Confronto Trend"
        )
        assert invalid_trend["paragraphs"] == default_trend["paragraphs"]

    def test_forecast_section_contains_all_scenarios(self):
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast)
        forecast_section = next(
            s for s in content["sections"] if s["heading"] == f"Previsione {forecast.target_month_label}"
        )
        items_text = " ".join(forecast_section["items"])
        assert "€450.00" in items_text
        assert "€405.00" in items_text
        assert "€517.50" in items_text

    def test_locked_from_section_is_set(self):
        # Deve bloccare TUTTE le sezioni (0), non solo da quella successiva:
        # sections[0] è la tabella categorie con i numeri reali, che per un
        # utente Free bloccato non deve mai restare in chiaro (vedi review
        # sul paywall — locked_from_section=1 lasciava passare la tabella).
        report = _make_report()
        forecast = _make_forecast()
        content = ReportBuilder.build_content(report, forecast)
        assert content["locked_from_section"] == 0
