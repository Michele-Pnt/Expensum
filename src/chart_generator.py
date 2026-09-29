"""
src/chart_generator.py — Generazione di grafici da inviare via Telegram.
"""

import os
import uuid
import logging

from src.data_processor import TrendReport, CategoryBudgetResult

logger = logging.getLogger("financial_agent.chart_generator")

# Colori dei grafici dal brand kit (dark rebrand 2026-08-08). Il brand ne
# prescrive due per i grafici: Platino come neutro, Turchese come accento
# ("Grafici lineari in #B0B5B9 con evidenziazioni in #5FC4CB"). Prima qui
# c'erano una palette Nord messa a mano e le palette seaborn "pastel"/"muted",
# con sfondo #1e1e2e invece del Blu Profondo.
BRAND_GROUND = "#1C363D"   # Blu Profondo, sfondo
BRAND_ACCENT = "#5FC4CB"   # Turchese, serie in evidenza
BRAND_NEUTRAL = "#B0B5B9"  # Platino, serie di confronto, assi, griglia
BRAND_INK = "#E9F1EA"      # Bianco Menta, testo
BRAND_GRID = "#3A5A61"     # Platino attenuato sul fondo scuro, griglia recessiva

class ChartGenerator:
    """Generatore di grafici a partire dal TrendReport, salvati come immagini temporanee."""

    def __init__(self, output_dir: str = "/tmp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self._style_ready = False

    def _load_plotting_libs(self):
        """Carica lazily matplotlib e seaborn, configura lo stile al primo uso."""
        import matplotlib.pyplot as plt
        import seaborn as sns
        if not self._style_ready:
            # "darkgrid" disegna una griglia piena che compete coi dati: la
            # skill dataviz vuole griglia e assi recessivi.
            sns.set_theme(style="ticks")
            plt.rcParams.update({
                "text.color": BRAND_INK,
                "axes.labelcolor": BRAND_NEUTRAL,
                "xtick.color": BRAND_NEUTRAL,
                "ytick.color": BRAND_NEUTRAL,
                "axes.edgecolor": BRAND_GRID,
                "grid.color": BRAND_GRID,
                "grid.linewidth": 0.6,
                "figure.facecolor": BRAND_GROUND,
                "axes.facecolor": BRAND_GROUND,
                "savefig.facecolor": BRAND_GROUND,
                "font.size": 12,
            })
            self._style_ready = True
        return plt, sns

    def _get_filepath(self, prefix: str) -> str:
        """Genera un percorso di file univoco nella cartella di output."""
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}.png"
        return os.path.join(self.output_dir, filename)

    def generate_all_charts(self, report: TrendReport) -> list[str]:
        """
        Genera tutti i grafici pertinenti e ritorna i percorsi dei file immagine.
        """
        paths = []
        try:
            cur = report.current_month
            if cur and cur.total > 0:
                p = self.generate_pie_chart(report)
                if p: paths.append(p)
                p = self.generate_bar_chart(report)
                if p: paths.append(p)
            
            if report.history:
                p = self.generate_line_chart(report)
                if p: paths.append(p)
                
            logger.info(f"Generati {len(paths)} grafici in {self.output_dir}")
        except Exception as e:
            logger.error(f"Errore durante la generazione dei grafici: {e}")
        return paths

    def generate_pie_chart(self, report: TrendReport) -> str:
        """Grafico a torta delle spese del mese corrente (Top N + Altro)."""
        plt, sns = self._load_plotting_libs()
        cur = report.current_month
        
        # Filtra categorie a zero
        categories = [(k, v) for k, v in cur.by_category.items() if v > 0]
        categories.sort(key=lambda x: x[1], reverse=True)
        
        if not categories:
            return ""

        # Mantieni le prime 6, compatta il resto in "Altro"
        labels = [c[0] for c in categories[:6]]
        sizes = [c[1] for c in categories[:6]]
        
        if len(categories) > 6:
            labels.append("Altro")
            sizes.append(sum(c[1] for c in categories[6:]))
            
        # Era una torta con la palette seaborn "pastel": con una categoria
        # dominante le fette piccole diventano schegge illeggibili, e sette
        # tinte diverse non stanno nel brand. A barre orizzontali le categorie
        # sono scritte sull'asse, quindi il colore non porta identita' e basta
        # una serie sola nell'accento.
        fig, ax = plt.subplots(figsize=(9, max(3.2, 0.62 * len(labels) + 1.2)))

        y_pos = list(range(len(labels)))
        # Le categorie arrivano ordinate per importo decrescente: invertendo
        # l'asse y la piu' grande resta in alto.
        ax.barh(y_pos, sizes, color=BRAND_ACCENT, height=0.58)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels)
        ax.invert_yaxis()

        total = sum(sizes) or 1.0
        for y, value in zip(y_pos, sizes):
            ax.text(
                value + total * 0.012, y,
                f"€{value:,.0f}".replace(",", "."),
                color=BRAND_NEUTRAL, va="center", fontsize=11,
            )

        ax.set_xlim(0, max(sizes) * 1.18)
        ax.set_xlabel("")
        ax.set_xticks([])
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0)

        ax.set_title(
            f"Dove sono finiti i soldi - {cur.label}",
            color=BRAND_INK, fontsize=16, pad=20, loc="left",
        )
        
        filepath = self._get_filepath("pie_chart")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return filepath

    def generate_bar_chart(self, report: TrendReport) -> str:
        """Grafico a barre: Confronto Spesa Attuale vs media storica per le categorie principali."""
        import pandas as pd
        plt, sns = self._load_plotting_libs()
        cur = report.current_month
        
        # Prepara dati per le categorie con spesa o con media (non a 0 entrambe)
        data = []
        all_cats = set(cur.by_category.keys()).union(set(cur.by_category_average.keys()))
        for cat in all_cats:
            amt = cur.by_category.get(cat, 0.0)
            avg = cur.by_category_average.get(cat, 0.0)
            if amt > 0 or avg > 0:
                data.append({"Categoria": cat, "Importo": amt, "Tipo": "Consumo Mese"})
                data.append({"Categoria": cat, "Importo": avg, "Tipo": "Media storica"})
                
        if not data:
            return ""

        df = pd.DataFrame(data)
        
        # Ordina mostrare solo le prime 8 categorie (basato sulla spesa mensile)
        top_cats = [c for c, _ in cur.top_categories(8)]
        df = df[df['Categoria'].isin(top_cats)]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(
            data=df, 
            x="Importo", 
            y="Categoria", 
            hue="Tipo", 
            palette={"Consumo Mese": BRAND_ACCENT, "Media storica": BRAND_NEUTRAL},
            ax=ax
        )
        
        ax.set_title("Spesa del mese vs media storica", color=BRAND_INK, fontsize=16, pad=15, loc="left")
        ax.set_xlabel("Importo (€)")
        ax.set_ylabel("")
        
        # Colori legende
        legend = ax.legend(frameon=True, facecolor=BRAND_GROUND, edgecolor=BRAND_GRID)
        plt.setp(legend.get_texts(), color=BRAND_INK)

        filepath = self._get_filepath("bar_chart")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return filepath

    def generate_line_chart(self, report: TrendReport) -> str:
        """Grafico a linee del trend storico (Totale speso per mese)."""
        plt, sns = self._load_plotting_libs()
        history_and_current = report.history + [report.current_month]
        
        # Filtra eventuali mesi vuoti
        data = [m for m in history_and_current if m.total > 0]
        if len(data) < 2:
            return "" # Troppo pochi dati per un trend
            
        labels = [m.label for m in data]
        totals = [m.total for m in data]
        # Usa indici numerici per evitare i warning matplotlib.category sulle stringhe
        x_pos = list(range(len(labels)))
        
        fig, ax = plt.subplots(figsize=(10, 5))
        
        # Linea del trend
        sns.lineplot(x=x_pos, y=totals, marker="o", linewidth=3, markersize=10, color=BRAND_ACCENT, ax=ax)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels)
        
        # Linea della media storica
        if report.historical_avg > 0:
            ax.axhline(y=report.historical_avg, color=BRAND_NEUTRAL, linestyle='--', linewidth=2, label=f"Media Storica ({report.historical_avg:.0f}€)")
            
        ax.set_title("Andamento delle spese", color=BRAND_INK, fontsize=16, pad=15, loc="left")
        ax.set_ylabel("Totale Speso (€)")
        ax.set_xlabel("")
        plt.xticks(rotation=45, ha='right')
        
        legend = ax.legend(frameon=True, facecolor=BRAND_GROUND, edgecolor=BRAND_GRID)
        plt.setp(legend.get_texts(), color=BRAND_INK)

        # Aggiungi le label numeriche sui punti
        for xi, y in zip(x_pos, totals):
            ax.text(xi, y + (max(totals)*0.03), f"€{y:.0f}", color=BRAND_NEUTRAL, ha="center")

        filepath = self._get_filepath("line_chart")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return filepath

    def generate_weekly_budget_table(
        self,
        budget_results: dict[str, CategoryBudgetResult],
        spent_last_week_by_cat: dict[str, float],
        title: str = "",
    ) -> str:
        """
        Genera una tabella PNG del budget settimanale per categoria.
        Colonne: Categoria | Ritmo recente | Speso nel mese | Ritmo consigliato | Stato
        """
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches

        sorted_cats = sorted(
            budget_results.items(),
            key=lambda x: x[1].budget_monthly,
            reverse=True,
        )
        n = len(sorted_cats)
        if n == 0:
            return ""

        # ── Palette ────────────────────────────────────────────────────────
        # Neutri e accento vengono dal brand kit. I tre colori di stato
        # (verde/giallo/rosso) restano quelli precedenti: il brand kit non
        # definisce una palette di stato, e la skill dataviz la vuole riservata
        # e distinta dall'accento, quindi qui non se ne inventa una. Da fissare
        # nel brand kit prima di toccarli.
        BG       = BRAND_GROUND
        SURFACE  = "#22424A"   # Blu Profondo schiarito, riga alternata
        OVERLAY  = "#2B4F58"   # Blu Profondo schiarito, traccia delle barre
        TEXT     = BRAND_INK
        SUBTEXT  = BRAND_NEUTRAL
        ACCENT   = BRAND_ACCENT
        GREEN    = "#a6e3a1"   # stato: in linea
        YELLOW   = "#f9e2af"   # stato: attenzione
        RED      = "#f38ba8"   # stato: fuori budget
        GREY     = "#6E8085"
        SEP      = BRAND_GRID

        SUBTITLE = "Ritmo consigliato = budget residuo ÷ settimane equivalenti rimaste"
        FOOTER   = "Modifica i tuoi budget con  /modify"

        # ── Layout ─────────────────────────────────────────────────────────
        FIG_W    = 11.0
        ROW_H    = 0.52
        HEADER_H = 0.80
        TITLE_H  = 0.48 if title else 0.0
        SUB_H    = 0.32
        LEGEND_H = 0.34
        FOOTER_H = 0.30
        PAD_V    = 0.20
        FIG_H    = PAD_V + TITLE_H + SUB_H + HEADER_H + n * ROW_H + LEGEND_H + FOOTER_H + PAD_V

        # (header_label, width_fraction, h_align)
        COLS = [
            ("Categoria",                0.26, "left"),
            ("Ritmo\nrecente",           0.16, "right"),
            ("Speso nel\nmese",          0.17, "right"),
            ("Ritmo\nconsigliato",       0.24, "right"),
            ("Stato",                    0.17, "center"),
        ]
        PAD_X = 0.014  # padding interno cella

        fig = plt.figure(figsize=(FIG_W, FIG_H))
        fig.patch.set_facecolor(BG)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, FIG_H)
        ax.axis("off")

        y = FIG_H - PAD_V

        # ── Titolo ─────────────────────────────────────────────────────────
        if title:
            ax.text(
                0.5, y - TITLE_H / 2, title,
                ha="center", va="center",
                color=TEXT, fontsize=14, fontweight="bold",
            )
            y -= TITLE_H

        # ── Subtitle / legenda ──────────────────────────────────────────────
        ax.text(
            0.5, y - SUB_H / 2, SUBTITLE,
            ha="center", va="center",
            color=SUBTEXT, fontsize=9, style="italic",
        )
        y -= SUB_H

        # ── Header ─────────────────────────────────────────────────────────
        x = 0.0
        for label, w, align in COLS:
            ax.add_patch(patches.Rectangle(
                (x, y - HEADER_H), w, HEADER_H,
                linewidth=0, facecolor=OVERLAY,
            ))
            tx = x + PAD_X if align == "left" else (x + w - PAD_X if align == "right" else x + w / 2)
            ax.text(
                tx, y - HEADER_H / 2, label,
                ha=align, va="center",
                color=ACCENT, fontsize=11, fontweight="bold", linespacing=1.5,
            )
            x += w

        # Linea separatrice sotto header
        ax.plot([0, 1], [y - HEADER_H, y - HEADER_H], color=ACCENT, linewidth=1.5)
        y -= HEADER_H

        # ── Righe dati ─────────────────────────────────────────────────────
        STATUS_COLOR = {"ok": GREEN, "attenzione": YELLOW, "sforato": RED}
        STATUS_LABEL = {
            "ok": "In linea",
            "attenzione": "Sopra ritmo",
            "sforato": "Budget superato",
        }
        STATUS_ICON  = {"ok": "✓", "attenzione": "!", "sforato": "✗"}

        for i, (cat, r) in enumerate(sorted_cats):
            row_bg = SURFACE if i % 2 == 0 else BG
            recent_pace = spent_last_week_by_cat.get(cat, r.recent_weekly_pace)
            if recent_pace == 0.0 and r.status != "sforato":
                s_color, s_label, s_icon = GREY, "Nessuna spesa", "⬜"
            else:
                s_color = STATUS_COLOR.get(r.status, SUBTEXT)
                s_label = STATUS_LABEL.get(r.status, r.status)
                s_icon  = STATUS_ICON.get(r.status, "?")

            cell_vals = [
                cat,
                f"€ {recent_pace:,.2f} / sett.",
                f"€ {r.spent_month:,.2f}",
                f"€ {r.limite_reale:,.2f} / sett.",
                None,  # status: disegnato a parte
            ]

            x = 0.0
            for j, ((_, w, align), val) in enumerate(zip(COLS, cell_vals)):
                ax.add_patch(patches.Rectangle(
                    (x, y - ROW_H), w, ROW_H,
                    linewidth=0, facecolor=row_bg,
                ))

                if j == 4:
                    # Pill colorata con icona + label
                    pill_w, pill_h = w * 0.82, ROW_H * 0.56
                    pill_x = x + (w - pill_w) / 2
                    pill_y = y - ROW_H / 2 - pill_h / 2
                    ax.add_patch(patches.FancyBboxPatch(
                        (pill_x, pill_y), pill_w, pill_h,
                        boxstyle="round,pad=0.008",
                        linewidth=0, facecolor=s_color, alpha=0.22,
                    ))
                    ax.add_patch(patches.FancyBboxPatch(
                        (pill_x, pill_y), pill_w, pill_h,
                        boxstyle="round,pad=0.008",
                        linewidth=1.2, edgecolor=s_color, facecolor="none",
                    ))
                    ax.text(
                        x + w / 2, y - ROW_H / 2,
                        f"{s_icon}  {s_label}",
                        ha="center", va="center",
                        color=s_color, fontsize=9.5, fontweight="bold",
                    )
                else:
                    tx = x + PAD_X if align == "left" else (x + w - PAD_X if align == "right" else x + w / 2)
                    ax.text(
                        tx, y - ROW_H / 2, val,
                        ha=align, va="center",
                        color=TEXT, fontsize=10,
                    )
                x += w

            # Linea separatrice leggera tra righe
            ax.plot([0, 1], [y - ROW_H, y - ROW_H], color=SEP, linewidth=0.4)
            y -= ROW_H

        # ── Legenda stati ──────────────────────────────────────────────────
        ax.plot([0.02, 0.98], [y, y], color=SEP, linewidth=0.6)
        y_leg = y - LEGEND_H / 2
        legend_items = [
            ("✓  In linea", GREEN, 0.25),
            ("!  Sopra ritmo", YELLOW, 0.50),
            ("✗  Budget superato", RED, 0.75),
        ]
        for label, color, xpos in legend_items:
            ax.text(
                xpos, y_leg, label,
                ha="center", va="center",
                color=color, fontsize=9.5, fontweight="bold",
            )
        y -= LEGEND_H

        # ── Footer ─────────────────────────────────────────────────────────
        ax.text(
            0.5, y - FOOTER_H / 2, FOOTER,
            ha="center", va="center",
            color=SUBTEXT, fontsize=9, style="italic",
        )

        filepath = self._get_filepath("weekly_budget_table")
        plt.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        return filepath
