"""
src/forecaster.py — Motore predittivo per la spesa del mese successivo.

Algoritmo:
1. Identifica le spese FISSE (abbonamenti): transazioni che ricorrono
   ogni mese con importo stabile (±5%) nella stessa categoria.
2. Calcola la media ponderata delle spese VARIABILI (più recenti = peso maggiore).
3. Applica un coefficiente di stagionalità mensile per aggiustare la previsione.
4. Produce un range: ottimistico (base - 10%), base, pessimistico (base + 15%).
"""

import logging
from calendar import month_name
from collections import defaultdict

from src.data_processor import MonthlySummary, TrendReport

logger = logging.getLogger("financial_agent.forecaster")


# Coefficienti stagionalità per mese (1.0 = media, >1 = mese più costoso)
# Personalizzabili in base alle proprie abitudini di spesa
SEASONALITY = {
    1: 1.05,   # Gennaio   — post-feste, capodanno
    2: 0.95,   # Febbraio  — mese corto
    3: 1.00,   # Marzo
    4: 1.00,   # Aprile
    5: 1.05,   # Maggio    — vacanze pasquali, uscite
    6: 1.10,   # Giugno    — inizio estate
    7: 1.15,   # Luglio    — vacanze estive
    8: 1.20,   # Agosto    — vacanze estive (picco)
    9: 1.05,   # Settembre — rientro, spese scolastiche
    10: 1.00,  # Ottobre
    11: 1.05,  # Novembre  — Black Friday
    12: 1.20,  # Dicembre  — Natale (picco)
}


class ForecastResult:
    """Risultato della previsione per il mese successivo."""

    def __init__(self):
        self.target_month_label: str = ""
        self.fixed_expenses: float = 0.0
        self.fixed_items: list[dict] = []
        self.variable_avg: float = 0.0
        self.seasonality_factor: float = 1.0
        self.base_forecast: float = 0.0
        self.optimistic_forecast: float = 0.0
        self.pessimistic_forecast: float = 0.0
        self.explanation: str = ""

    def to_prompt_text(self) -> str:
        """Serializza il forecast in testo strutturato per il prompt Gemini."""
        lines = [
            f"=== PREVISIONE MESE: {self.target_month_label} ===",
            f"Spese fisse identificate: €{self.fixed_expenses:.2f}",
        ]
        if self.fixed_items:
            for item in self.fixed_items:
                lines.append(f"  - {item['category']}: €{item['avg_amount']:.2f}/mese")
        lines += [
            f"Media spese variabili (ponderata): €{self.variable_avg:.2f}",
            f"Fattore stagionalità ({self.target_month_label[:3]}): x{self.seasonality_factor:.2f}",
            f"Previsione BASE: €{self.base_forecast:.2f}",
            f"Previsione OTTIMISTICA (-10%): €{self.optimistic_forecast:.2f}",
            f"Previsione PESSIMISTICA (+15%): €{self.pessimistic_forecast:.2f}",
            f"Nota: {self.explanation}",
        ]
        return "\n".join(lines)


class Forecaster:
    """Genera previsioni statistiche per la spesa del mese prossimo."""

    FIXED_TOLERANCE = 0.08   # Tolleranza ±8% per classificare una spesa come fissa
    FIXED_MIN_MONTHS = 3     # Almeno 3 mesi consecutivi per considerarla fissa

    def predict(self, report: TrendReport, next_month: int, next_year: int) -> ForecastResult:
        """
        Genera la previsione per il mese specificato.

        Args:
            report: TrendReport già elaborato dal DataProcessor
            next_month: Mese target (1-12)
            next_year: Anno target

        Returns:
            ForecastResult con range di previsione
        """
        result = ForecastResult()
        result.target_month_label = f"{month_name[next_month]} {next_year}"
        result.seasonality_factor = SEASONALITY.get(next_month, 1.0)

        all_months = report.history + ([report.current_month] if report.current_month else [])

        if not all_months:
            logger.warning("Nessun dato storico per la previsione.")
            result.explanation = "Dati insufficienti per una previsione accurata."
            return result

        # 1. Identifica spese fisse
        fixed_cats, fixed_total = self._identify_fixed_expenses(all_months)
        result.fixed_expenses = fixed_total
        result.fixed_items = fixed_cats

        # 2. Calcola media ponderata spese variabili (senza le fisse)
        result.variable_avg = self._weighted_variable_avg(all_months, fixed_cats)

        # 3. Previsione base = fisse + variabili * stagionalità
        raw_base = result.fixed_expenses + result.variable_avg
        result.base_forecast = round(raw_base * result.seasonality_factor, 2)
        result.optimistic_forecast = round(result.base_forecast * 0.90, 2)
        result.pessimistic_forecast = round(result.base_forecast * 1.15, 2)

        result.explanation = (
            f"Basato su {len(all_months)} mesi di dati. "
            f"Spese fisse ({len(fixed_cats)} categorie) + variabili medie, "
            f"aggiustato per stagionalità di {result.target_month_label[:3]}."
        )

        logger.info(
            f"Previsione {result.target_month_label}: "
            f"base=€{result.base_forecast:.2f} "
            f"[€{result.optimistic_forecast:.2f} – €{result.pessimistic_forecast:.2f}]"
        )
        return result

    def _identify_fixed_expenses(
        self, months: list[MonthlySummary]
    ) -> tuple[list[dict], float]:
        """
        Identifica le categorie di spesa fissa (ricorrenti e stabili).
        Una categoria è "fissa" se appare in almeno FIXED_MIN_MONTHS mesi
        con una variazione massima di ±FIXED_TOLERANCE rispetto alla propria media.
        """
        cat_amounts: dict[str, list[float]] = defaultdict(list)
        n_months = len(months)

        for m in months:
            for cat, amt in m.by_category.items():
                cat_amounts[cat].append(amt)

        fixed_items = []
        total_fixed = 0.0

        for cat, amounts in cat_amounts.items():
            if len(amounts) < min(self.FIXED_MIN_MONTHS, n_months):
                continue
            avg = sum(amounts) / len(amounts)
            if avg == 0:
                continue
            # Verifica che tutti i valori siano entro la tolleranza
            is_stable = all(
                abs(a - avg) / avg <= self.FIXED_TOLERANCE for a in amounts
            )
            if is_stable:
                fixed_items.append({"category": cat, "avg_amount": avg})
                total_fixed += avg

        logger.info(
            f"Spese fisse identificate: {len(fixed_items)} categorie, "
            f"totale €{total_fixed:.2f}/mese"
        )
        return fixed_items, total_fixed

    def _weighted_variable_avg(
        self, months: list[MonthlySummary], fixed_items: list[dict]
    ) -> float:
        """
        Calcola la media ponderata delle spese variabili.
        I mesi più recenti hanno peso maggiore (pesi lineari).
        """
        fixed_cats = {item["category"] for item in fixed_items}
        n = len(months)
        if n == 0:
            return 0.0

        weighted_sum = 0.0
        weight_total = 0.0

        for i, m in enumerate(months):
            # Peso lineare: mese più recente = peso n, più vecchio = peso 1
            weight = i + 1
            variable_total = sum(
                amt for cat, amt in m.by_category.items() if cat not in fixed_cats
            )
            weighted_sum += variable_total * weight
            weight_total += weight

        return weighted_sum / weight_total if weight_total > 0 else 0.0
