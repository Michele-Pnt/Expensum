"""
src/report_builder.py — Assembla il report finale per Telegram.

In modalità dry-run (o in caso di fallimento Gemini), usa i dati statistici
locali per costruire un report di fallback senza chiamare le API esterne.
"""

import logging
from calendar import month_name
from datetime import date

from src.data_processor import TrendReport
from src.forecaster import ForecastResult

logger = logging.getLogger("financial_agent.report_builder")


class ReportBuilder:
    """Assembla e formatta il report Markdown per Telegram."""

    @staticmethod
    def build_fallback_report(
        report: TrendReport, forecast: ForecastResult, accounts: list[dict] = None
    ) -> str:
        """
        Costruisce un report Markdown completo usando SOLO i dati statistici
        locali (nessuna chiamata Gemini). Utile per dry-run o fallback.
        """
        cur = report.current_month
        lines = []

        # 1. Riepilogo
        lines.append(f"📊 *Riepilogo {cur.label}*")
        lines.append(f"Spesa totale: *€{cur.total:.2f}*")
        lines.append(f"Entrate totali: *€{report.total_income:.2f}*")
        
        tot_acc = sum(a.get('current_balance', 0.0) for a in accounts) if accounts else 0.0
        lines.append(f"🏦 Denaro sui conti: *€{tot_acc:.2f}*")
        
        # In mancanza del dato esatto di Notion in args passati al costruttore, usiamo n/d per il momento
        # (potremmo volerlo passare tra gli argomenti se necessario)
        lines.append(f"Risparmio mensile: *(Calcolato da Notion)*")
        
        lines.append("\n*Spesa per categorie:*")
        c_list = sorted(cur.by_category.items(), key=lambda x: x[1], reverse=True)
        for cat, amt in c_list:
            if amt > 0:
                pct = (amt / cur.total * 100) if cur.total > 0 else 0
                lines.append(f"  • {cat}: €{amt:.2f} ({pct:.1f}%)")

        # 2. Analisi e Confronto Trend
        lines.append(f"\n---\n📉 *Analisi e Confronto Trend*\n")
        
        # Spese
        if report.historical_avg > 0:
            delta_eur = cur.total - report.historical_avg
            sign = "+" if delta_eur >= 0 else ""
            lines.append(
                f"- *Spese*: La spesa è in *{report.trend_direction}* vs media storica. "
                f"La media è €{report.historical_avg:.2f} ({sign}€{delta_eur:.2f}, {report.delta_pct:+.1f}%)."
            )
        else:
            lines.append("- *Spese*: Dati storici insufficienti.")
            
        # Entrate & Risparmio
        lines.append("- *Entrate*: Statistiche locali non comparabili pienamente.")
        lines.append("- *Risparmio*: Dato elaborato esternamente (vedi app).")
        
        # Categorie
        lines.append("- *Categorie*: ")
        for cat, amt in list(cur.by_category.items())[:3]:
            avg_notion = cur.by_category_average.get(cat, 0.0)
            if amt > 0 and avg_notion > 0:
                lines.append(f"    • {cat}: speso €{amt:.2f} vs media €{avg_notion:.2f}")

        # 3. Forecast
        lines.append(f"\n---\n🔮 *Previsione {forecast.target_month_label}*\n")
        lines.append(f"Stima ottimistica: *€{forecast.optimistic_forecast:.2f}*")
        lines.append(f"Stima base: *€{forecast.base_forecast:.2f}*")
        lines.append(f"Stima pessimistica: *€{forecast.pessimistic_forecast:.2f}*")

        if forecast.fixed_items:
            lines.append(
                f"\n_Spese fisse identificate ({len(forecast.fixed_items)}): "
                f"€{forecast.fixed_expenses:.2f}/mese_"
            )

        # Consigli base (statistici, senza Gemini)
        lines.append("\n---\n💡 *Consigli Azionabili*\n")
        tips = ReportBuilder._generate_basic_tips(report, forecast)
        for i, tip in enumerate(tips, 1):
            lines.append(f"{i}️⃣ {tip}")

        lines.append(
            "\n---\n_Report generato automaticamente dall'Agente Finanziario 🤖_"
        )

        return "\n".join(lines)

    @staticmethod
    def _generate_basic_tips(report: TrendReport, forecast: ForecastResult) -> list[str]:
        """Genera 3 consigli azionabili basati sui dati statistici."""
        tips = []
        cur = report.current_month

        # Consiglio 1: basato sul trend generale
        if report.delta_pct > 10:
            tips.append(
                f"La tua spesa totale è cresciuta del {report.delta_pct:.0f}% rispetto "
                f"alla media storica. Considera di fissare un budget mensile di "
                f"€{report.historical_avg:.0f} più vicino alla tua media."
            )
        elif report.historical_avg > 0:
            tips.append(
                f"Stai gestendo bene le spese. Per ottimizzare ulteriormente, "
                f"punta a mantenere la spesa mensile sotto €{report.historical_avg:.0f} "
                f"(la tua media storica)."
            )

        # Consiglio 2: basato sulla categoria più costosa
        top_cats = cur.top_categories(1)
        if top_cats:
            cat_name, cat_amt = top_cats[0]
            cat_pct = (cat_amt / cur.total * 100) if cur.total > 0 else 0
            if cat_pct > 30:
                tips.append(
                    f"La categoria *{cat_name}* rappresenta il {cat_pct:.0f}% del totale "
                    f"(€{cat_amt:.0f}). Valuta se ci sono margini di riduzione in quest'area."
                )

        # Fallback generici se non ci sono dati sufficienti
        while len(tips) < 3:
            generics = [
                "Monitora le piccole spese ricorrenti: spesso sfuggono ma si accumulano.",
                "Confronta i prezzi degli abbonamenti attivi: potresti trovare piani migliori.",
                "Imposta un fondo di emergenza pari a 3 mesi di spese medie.",
            ]
            for g in generics:
                if g not in tips:
                    tips.append(g)
                if len(tips) == 3:
                    break

        return tips[:3]
