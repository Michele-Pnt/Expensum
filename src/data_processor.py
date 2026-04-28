"""
src/data_processor.py — Elaborazione, aggregazione e analisi statistica
delle transazioni di spesa estratte da Notion.

Funzionalità:
- Aggregazione per mese e categoria
- Calcolo statistiche mensili (totale, media, top categorie)
- Analisi dei trend (confronto mese attuale vs media storica)
- Rilevamento anomalie (variazioni sopra soglia configurabile)
- Compattazione dati in testo strutturato per il prompt Gemini
"""

import logging
from calendar import month_name
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from config import Config

logger = logging.getLogger("financial_agent.processor")


# ---------------------------------------------------------------------------
# Strutture dati di output
# ---------------------------------------------------------------------------

class MonthlySummary:
    """Riepilogo delle spese di un singolo mese."""

    def __init__(self, year: int, month: int):
        self.year = year
        self.month = month
        self.label = f"{month_name[month]} {year}"
        self.total: float = 0.0
        self.by_category_average: dict[str, float] = {}
        self.transaction_count: int = 0
        self.daily_avg: float = 0.0

    def top_categories(self, n: int = 5) -> list[tuple[str, float]]:
        """Ritorna le top N categorie per importo, ordinate discendente."""
        return sorted(self.by_category.items(), key=lambda x: x[1], reverse=True)[:n]

    def __repr__(self) -> str:
        return f"MonthlySummary({self.label}, totale={self.total:.2f}€)"


class TrendReport:
    """Risultato dell'analisi dei trend."""

    def __init__(self):
        self.current_month: Optional[MonthlySummary] = None
        self.history: list[MonthlySummary] = []
        self.historical_avg: float = 0.0
        self.delta_pct: float = 0.0          # % variazione rispetto alla media storica
        self.trend_direction: str = "stabile" # "crescita" | "contrazione" | "stabile"
        self.total_income: float = 0.0
        self.incomes: list[dict] = []


# ---------------------------------------------------------------------------
# DataProcessor principale
# ---------------------------------------------------------------------------

class DataProcessor:
    """Elabora le transazioni grezze e produce statistiche e analisi."""

    def __init__(self):
        self.history_months = Config.HISTORY_MONTHS

    # ------------------------------------------------------------------
    # Punto d'ingresso principale
    # ------------------------------------------------------------------
    def process(
        self,
        transactions: list[dict],
        target_year: int,
        target_month: int,
        incomes: list[dict] = None,
    ) -> TrendReport:
        """
        Elabora tutte le transazioni e produce un TrendReport completo.

        Args:
            transactions: Lista di dict {date, category, name, amount}
            target_year: Anno del mese da analizzare
            target_month: Mese da analizzare (1-12)

        Returns:
            TrendReport con mese corrente, storico e anomalie
        """
        if not transactions:
            logger.warning("Nessuna transazione ricevuta!")
            return TrendReport()

        df = self._to_dataframe(transactions)
        monthly_summaries = self._aggregate_by_month(df)

        report = TrendReport()
        report.current_month = monthly_summaries.get((target_year, target_month))

        if report.current_month is None:
            logger.warning(
                f"Nessuna transazione trovata per {month_name[target_month]} {target_year}"
            )
            report.current_month = MonthlySummary(target_year, target_month)

        # Storico: ultimi N mesi ESCLUSO il mese corrente
        hist_keys = sorted(
            [k for k in monthly_summaries if k != (target_year, target_month)]
        )[-self.history_months:]
        report.history = [monthly_summaries[k] for k in hist_keys]

        # Trend globale
        if report.history:
            report.historical_avg = sum(m.total for m in report.history) / len(report.history)
            if report.historical_avg > 0:
                report.delta_pct = (
                    (report.current_month.total - report.historical_avg)
                    / report.historical_avg
                ) * 100
                if report.delta_pct > 5:
                    report.trend_direction = "crescita"
                elif report.delta_pct < -5:
                    report.trend_direction = "contrazione"
                else:
                    report.trend_direction = "stabile"

        if incomes:
            # Filtra le entrate fittizie
            filtered_incomes = [
                inc for inc in incomes 
                if inc.get("name") not in ["Movimenti", "Pareggio Conti"]
            ]
            report.incomes = filtered_incomes
            report.total_income = sum(
                inc["amount"] for inc in filtered_incomes 
                if inc["date"].year == target_year and inc["date"].month == target_month
            )

        logger.info(
            f"Elaborazione completata: {report.current_month.label}, "
            f"totale_spese={report.current_month.total:.2f}€, "
            f"totale_entrate={report.total_income:.2f}€, "
            f"trend={report.trend_direction} ({report.delta_pct:+.1f}%)"
        )
        return report

    # ------------------------------------------------------------------
    # Aggregazione per mese
    # ------------------------------------------------------------------
    def _to_dataframe(self, transactions: list[dict]):
        import pandas as pd
        df = pd.DataFrame(transactions)
        
        # Filtra le finte spese (trasferimenti/pareggi)
        df = df[~df["category"].isin(["Movimenti", "Pareggio Conti"])]
        
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        df["month"] = df["date"].dt.month
        df["amount"] = df["amount"].abs()  # Normalizza a positivo
        return df

    def _aggregate_by_month(self, df) -> dict[tuple, MonthlySummary]:
        """Aggrega le transazioni per (anno, mese) e ritorna un dict di MonthlySummary."""
        import pandas as pd
        summaries: dict[tuple, MonthlySummary] = {}

        for (year, month), group in df.groupby(["year", "month"]):
            summary = MonthlySummary(int(year), int(month))
            summary.total = float(group["amount"].sum())
            summary.transaction_count = len(group)

            # Giorni nel mese per media giornaliera
            days_in_month = (
                pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
            ).day
            summary.daily_avg = summary.total / days_in_month

            # Aggregazione per categoria
            cat_totals = group.groupby("category")["amount"].sum()
            summary.by_category = cat_totals.to_dict()
            
            # Recupero medie Notion per le categorie di questo mese
            if "category_average" in group.columns:
                cat_averages = group.groupby("category")["category_average"].first()
                summary.by_category_average = cat_averages.to_dict()

            summaries[(int(year), int(month))] = summary

        return summaries



    # ------------------------------------------------------------------
    # Compattazione dati per il prompt Gemini
    # ------------------------------------------------------------------
    def to_prompt_text(self, report: TrendReport) -> str:
        """
        Compatta il TrendReport in un unico blocco di testo strutturato
        da inserire nel prompt Gemini, minimizzando i token usati.
        """
        lines = []
        cur = report.current_month

        lines.append(f"=== MESE ANALIZZATO: {cur.label} ===")
        lines.append(f"Spese totali: €{cur.total:.2f}")
        lines.append(f"Entrate totali (Income): €{report.total_income:.2f}")
        lines.append(f"Numero transazioni spesa: {cur.transaction_count}")
        lines.append(f"Media giornaliera spese: €{cur.daily_avg:.2f}")
        lines.append("")
        lines.append("SPESE PER CATEGORIA MESE ATTUALE VS BUDGET/MEDIA (da Notion):")
        for cat, amt in sorted(cur.by_category.items(), key=lambda x: x[1], reverse=True):
            pct = (amt / cur.total * 100) if cur.total > 0 else 0
            avg_notion = cur.by_category_average.get(cat, 0.0)
            avg_info = f"vs Media Notion €{avg_notion:.2f}" if avg_notion > 0 else "(no media Notion)"
            lines.append(f"  {cat}: €{amt:.2f} ({pct:.1f}%) {avg_info}")

        lines.append("")
        lines.append(f"=== STORICO ULTIMI {len(report.history)} MESI ===")
        lines.append(f"Media mensile storica: €{report.historical_avg:.2f}")
        lines.append(f"Variazione vs media: {report.delta_pct:+.1f}% ({report.trend_direction})")
        lines.append("")
        lines.append("DETTAGLIO MESI PRECEDENTI:")
        for m in report.history:
            lines.append(f"  {m.label}: €{m.total:.2f} ({m.transaction_count} transazioni)")



        return "\n".join(lines)
