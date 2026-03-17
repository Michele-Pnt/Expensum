"""
src/chart_generator.py — Generazione di grafici da inviare via Telegram.
"""

import os
import uuid
import logging
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

from src.data_processor import TrendReport

logger = logging.getLogger("financial_agent.chart_generator")

class ChartGenerator:
    """Generatore di grafici a partire dal TrendReport, salvati come immagini temporanee."""

    def __init__(self, output_dir: str = "/tmp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Imposta lo stile di base di Seaborn
        sns.set_theme(style="darkgrid", palette="muted")
        # Colori adatti per visualizzazione chiara anche in dark mode
        plt.rcParams.update({
            "text.color": "white",
            "axes.labelcolor": "white",
            "xtick.color": "white",
            "ytick.color": "white",
            "axes.edgecolor": "white",
            "figure.facecolor": "#1e1e2e",    # Sfondo scuro elegante
            "axes.facecolor": "#1e1e2e",
            "font.size": 12
        })

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
