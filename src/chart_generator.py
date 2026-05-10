"""
src/chart_generator.py — Generazione di grafici da inviare via Telegram.
"""

from PIL import GimpGradientFile
import os
import uuid
import logging

from src.data_processor import TrendReport, CategoryBudgetResult

logger = logging.getLogger("financial_agent.chart_generator")

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
            sns.set_theme(style="darkgrid", palette="muted")
            plt.rcParams.update({
                "text.color": "white",
                "axes.labelcolor": "white",
                "xtick.color": "white",
                "ytick.color": "white",
                "axes.edgecolor": "white",
                "figure.facecolor": "#1e1e2e",
                "axes.facecolor": "#1e1e2e",
                "font.size": 12
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
            
        fig, ax = plt.subplots(figsize=(8, 8))
        
        # Scegli una palette Seaborn
        colors = sns.color_palette("pastel")[0:len(labels)]
        
        wedges, texts, autotexts = ax.pie(
            sizes, 
            labels=labels, 
            autopct='%1.1f%%',
            startangle=140, 
            colors=colors,
            textprops=dict(color="w")
        )
        for autotext in autotexts:
            autotext.set_color('#1e1e2e')
            autotext.set_weight('bold')

        ax.set_title(f"Suddivisione Spese - {cur.label}", color="white", fontsize=16, pad=20)
        
        filepath = self._get_filepath("pie_chart")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return filepath

    def generate_bar_chart(self, report: TrendReport) -> str:
        """Grafico a barre: Confronto Spesa Attuale vs Media Notion per le Top categorie."""
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
                data.append({"Categoria": cat, "Importo": avg, "Tipo": "Media Notion"})
                
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
            palette={"Consumo Mese": "#ff8888", "Media Notion": "#88c0d0"},
            ax=ax
        )
        
        ax.set_title("Spesa vs Buffer Mensile", color="white", fontsize=16, pad=15)
        ax.set_xlabel("Importo (€)")
        ax.set_ylabel("")
        
        # Colori legende
        legend = ax.legend(frameon=True, facecolor="#2e3440", edgecolor="none")
        plt.setp(legend.get_texts(), color='w')

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
        sns.lineplot(x=x_pos, y=totals, marker="o", linewidth=3, markersize=10, color="#a3be8c", ax=ax)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels)
        
        # Linea della media storica
        if report.historical_avg > 0:
            ax.axhline(y=report.historical_avg, color="#bf616a", linestyle='--', linewidth=2, label=f"Media Storica ({report.historical_avg:.0f}€)")
            
        ax.set_title("Andamento Storico Spese", color="white", fontsize=16, pad=15)
        ax.set_ylabel("Totale Speso (€)")
        ax.set_xlabel("")
        plt.xticks(rotation=45, ha='right')
        
        legend = ax.legend(frameon=True, facecolor="#2e3440", edgecolor="none")
        plt.setp(legend.get_texts(), color='w')

        # Aggiungi le label numeriche sui punti
        for xi, y in zip(x_pos, totals):
            ax.text(xi, y + (max(totals)*0.03), f"€{y:.0f}", color="white", ha="center")

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
        Colonne: Categoria | Settimana scorsa | Speso nel mese | Obiettivo per settimana | Stato
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
        BG       = "#1e1e2e"
        SURFACE  = "#313244"
        OVERLAY  = "#45475a"
        TEXT     = "#cdd6f4"
        SUBTEXT  = "#a6adc8"
        ACCENT   = "#89b4fa"
        GREEN    = "#a6e3a1"
        YELLOW   = "#f9e2af"
        RED      = "#f38ba8"
        GREY     = "#6c7086"
        SEP      = "#585b70"

        SUBTITLE = "Obiettivo sett. = budget residuo ÷ settimane rimaste nel mese"
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
            ("Settimana\nscorsa",        0.16, "right"),
            ("Speso nel\nmese",          0.17, "right"),
            ("Obiettivo\nper settimana", 0.24, "right"),
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
        STATUS_LABEL = {"ok": "OK", "attenzione": "Attenzione", "sforato": "Sforato"}
        STATUS_ICON  = {"ok": "✓", "attenzione": "!", "sforato": "✗"}

        for i, (cat, r) in enumerate(sorted_cats):
            row_bg = SURFACE if i % 2 == 0 else BG
            last_week = spent_last_week_by_cat.get(cat, 0.0)
            if last_week == 0.0:
                s_color, s_label, s_icon = GREY, "Nessuna spesa", "⬜"
            else:
                s_color = STATUS_COLOR.get(r.status, SUBTEXT)
                s_label = STATUS_LABEL.get(r.status, r.status)
                s_icon  = STATUS_ICON.get(r.status, "?")

            cell_vals = [
                cat,
                f"€ {last_week:,.2f}",
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
            ("✓  OK", GREEN, 0.25),
            ("!  Attenzione", YELLOW, 0.50),
            ("✗  Sforato", RED, 0.75),
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
