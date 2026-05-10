"""
scripts/benchmark_ocr.py — Benchmark qualità OCR su scontrini sintetici a difficoltà crescente.

30 scontrini generati con PIL (ground truth nota) + 4 varianti preprocessing:
  1. Baseline   — pipeline attuale (ocr_client.py)
  2. PSM-6      — Tesseract PSM 6 (blocco uniforme di testo)
  3. Deskew     — raddrizzamento angolo + upscale 1200px
  4. Otsu       — binarizzazione Otsu (threshold adattivo)

Uso:
  cd Finance-Agents
  python scripts/benchmark_ocr.py
  python scripts/benchmark_ocr.py --save-images      # salva le immagini generate in logs/ocr_images/
  python scripts/benchmark_ocr.py --difficulty easy   # solo casi facili
  python scripts/benchmark_ocr.py --show-failures     # stampa solo i casi falliti
"""

import argparse
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

console = Console(record=True)

# ---------------------------------------------------------------------------
# FONT
# ---------------------------------------------------------------------------
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# DATASET: 30 scontrini con ground truth
# ---------------------------------------------------------------------------

@dataclass
class Receipt:
    store: str
    items: list[tuple[str, str]]   # (nome, prezzo string)
    total: str
    difficulty: str                 # "easy" | "medium" | "hard"
    label: str                      # etichetta breve per la tabella


_RECEIPTS: list[Receipt] = [
    # ── EASY (10) — chiari, alta risoluzione, nessun disturbo ──────────────
    Receipt("Esselunga", [("Pane integrale", "1.29"), ("Latte fresco", "1.45"), ("Uova x6", "2.89")],
            "5.63", "easy", "supermercato base"),
    Receipt("Esselunga", [("Pasta Barilla 500g", "0.99"), ("Sugo pomodoro", "1.35"), ("Olio EVO", "5.49"),
                          ("Vino rosso", "4.99"), ("Acqua naturale x6", "2.10")],
            "14.92", "easy", "spesa media"),
    Receipt("McDonald's", [("Big Mac", "5.50"), ("Patatine M", "2.50"), ("Coca-Cola M", "2.00"),
                           ("McFlurry", "2.80")], "12.80", "easy", "fast food"),
    Receipt("IKEA", [("Cornice 30x40", "4.99"), ("Candela profumata", "3.99"), ("Tovagliette x4", "5.99")],
            "14.97", "easy", "arredamento"),
    Receipt("Farmacia Sant'Anna", [("Aspirina 20cpr", "3.50"), ("Vitamina C", "6.90"), ("Cerotti", "2.20")],
            "12.60", "easy", "farmacia"),
    Receipt("Shell", [("Benzina 30L", "51.90"), ("Acqua 0.5L", "1.50")],
            "53.40", "easy", "benzina"),
    Receipt("Libreria Mondadori", [("La citta' incantata", "15.90"), ("Agenda 2025", "9.99")],
            "25.89", "easy", "libreria"),
    Receipt("Trattoria da Luigi", [("Tagliatelle al ragu'", "12.00"), ("Vino della casa 0.25L", "4.50"),
                                   ("Tiramisu'", "5.00"), ("Caffe'", "1.50"), ("Coperto", "2.00")],
            "25.00", "easy", "ristorante"),
    Receipt("Zara", [("T-shirt bianca S", "17.95"), ("Jeans slim 32", "39.95")],
            "57.90", "easy", "abbigliamento"),
    Receipt("Trenitalia", [("Milano-Roma Frecce 1cl", "89.90"), ("Prenotazione", "10.00")],
            "99.90", "easy", "treno"),

    # ── MEDIUM (10) — leggero blur, rotazione ±5°, rumore moderato ─────────
    Receipt("Conad", [("Biscotti digestive", "1.79"), ("Yogurt greco x4", "3.20"), ("Prosciutto 100g", "2.49"),
                      ("Mozzarella", "1.29"), ("Banana 1kg", "1.10")],
            "9.87", "medium", "spesa rotaz+blur"),
    Receipt("Bar Central", [("Cappuccino", "1.60"), ("Cornetto", "1.20"), ("Succo frutta", "2.50")],
            "5.30", "medium", "bar sfocato"),
    Receipt("Decathlon", [("Pallone calcio", "19.99"), ("Borraccia 750ml", "12.99"), ("Calzini sport x3", "9.99")],
            "42.97", "medium", "sport blur"),
    Receipt("Iper", [("Detersivo piatti 1L", "2.99"), ("Ammorbidente", "3.49"), ("Spugne x3", "2.19"),
                     ("Carta igienica x12", "4.99"), ("Sacchetti rifiuto", "1.89")],
            "15.55", "medium", "ipermercato blur"),
    Receipt("Coop", [("Filetto di salmone 200g", "5.99"), ("Insalata mista", "1.49"),
                     ("Limoni x4", "1.19"), ("Burro 250g", "2.89")],
            "11.56", "medium", "supermercato rotaz"),
    Receipt("Pizzeria Napule", [("Margherita", "8.00"), ("Diavola", "9.50"), ("Birra Peroni", "4.50"),
                                ("Coperto x2", "4.00")],
            "26.00", "medium", "pizzeria blur"),
    Receipt("Lidl", [("Chips patatine", "0.99"), ("Biscotti farro", "1.29"), ("Latte UHT x2", "1.78"),
                     ("Tonno sott'olio x3", "2.37"), ("Succo arancia 2L", "1.99")],
            "8.42", "medium", "discount blur"),
    Receipt("H&M", [("Felpa con cappuccio M", "24.99"), ("Calze x5 paia", "9.99"), ("Cintura", "14.99")],
            "49.97", "medium", "abbigliamento noise"),
    Receipt("Autogrill", [("Panino al prosciutto", "5.50"), ("Caffe' doppio", "2.10"),
                          ("Acqua 0.5L", "2.30"), ("Giornale", "1.50")],
            "11.40", "medium", "autostrada blur"),
    Receipt("Douglas", [("Profumo EDT 50ml", "49.99"), ("Crema viso", "23.90")],
            "73.89", "medium", "profumeria rotaz"),

    # ── HARD (10) — forte blur, rotaz ±15°, bassa luce, contrasto ridotto ──
    Receipt("Esselunga", [("Spesa settimanale", "87.43")],
            "87.43", "hard", "scontrino sbiadito"),
    Receipt("Tabacchi", [("Sigarette Marlboro", "6.00"), ("Gratta e vinci", "5.00"),
                          ("Ricarica tel.", "10.00")],
            "21.00", "hard", "tabacchi basso contrasto"),
    Receipt("Kiosk", [("Acqua 0.5L", "1.00"), ("Gelato stecco", "2.50")],
            "3.50", "hard", "chiosco foto storta"),
    Receipt("Officine Mechini", [("Tagliando auto", "120.00"), ("Filtro olio", "25.90"),
                                  ("Manodopera", "60.00")],
            "205.90", "hard", "meccanico scuro"),
    Receipt("Farmacia Centrale", [("Ibuprofene 400mg", "4.90"), ("Collirio", "8.50"),
                                   ("Cerotto medicato", "5.20")],
            "18.60", "hard", "farmacia stropicciata"),
    Receipt("Trattoria Belveder", [("Risotto funghi porcini", "14.00"), ("Tagliata manzo 250g", "22.00"),
                                    ("Vino Barolo 0.5L", "18.00"), ("Dolce del giorno", "7.00"),
                                    ("Coperto x2", "6.00"), ("Caffe' x2", "3.00")],
            "70.00", "hard", "cena cara foto sfocata"),
    Receipt("Mercatino dell'usato", [("Lampada vintage", "15.00"), ("Libri x5", "8.00")],
            "23.00", "hard", "mercatino rumore"),
    Receipt("Bricofer", [("Silicone sigillante", "6.99"), ("Tasselli Ø10 x100", "4.99"),
                          ("Viti acciaio x50", "3.49"), ("Cartuccia vernice", "14.99")],
            "30.46", "hard", "ferramenta scuro"),
    Receipt("SuperG", [("Carne macinata 500g", "4.99"), ("Pomodori pelati x4", "2.80"),
                        ("Formaggio parmigiano 200g", "4.50"), ("Cipolle 1kg", "1.49")],
            "13.78", "hard", "super scaduto foto buia"),
    Receipt("Palestra FitLife", [("Abbonamento mensile", "45.00")],
            "45.00", "hard", "abbonamento foto sgranata"),
]


# ---------------------------------------------------------------------------
# GENERATORE IMMAGINI SINTETICHE
# ---------------------------------------------------------------------------

_RECEIPT_WIDTH = 480   # larghezza scontrino termico tipica in pixel


def _render_receipt_base(receipt: Receipt, font_size: int = 18) -> Image.Image:
    """Genera un'immagine bianca con il testo dello scontrino."""
    font = _load_font(font_size)
    font_bold = _load_font(font_size + 2)

    line_height = font_size + 6
    sep = "=" * 38
    lines: list[tuple[str, bool]] = []   # (testo, grassetto)

    lines.append((receipt.store.upper().center(38), True))
    lines.append(("Via Roma 1, Milano", False))
    lines.append(("Tel: 02-12345678", False))
    lines.append((sep, False))
    lines.append(("SCONTRINO FISCALE", True))
    lines.append(("-" * 38, False))

    for name, price in receipt.items:
        # tronca il nome se troppo lungo
        max_name = 30 - len(price)
        display_name = name[:max_name] if len(name) > max_name else name
        padding = 38 - len(display_name) - len(price)
        lines.append((display_name + " " * max(1, padding) + price, False))

    lines.append((sep, False))
    tot_str = f"TOTALE EUR      {receipt.total:>8}"
    lines.append((tot_str, True))
    lines.append(("-" * 38, False))
    lines.append(("IVA 22% inclusa", False))
    lines.append(("Grazie e arrivederci!", False))
    lines.append(("", False))
    lines.append(("2024-03-15  14:32", False))
    lines.append(("Scontrino n. 00247", False))

    height = len(lines) * line_height + 40
    img = Image.new("RGB", (_RECEIPT_WIDTH, height), color=(252, 252, 252))
    draw = ImageDraw.Draw(img)

    y = 20
    for text, bold in lines:
        f = font_bold if bold else font
        draw.text((20, y), text, fill=(30, 30, 30), font=f)
        y += line_height

    return img


def _apply_easy(img: Image.Image, rng: random.Random) -> Image.Image:
    """Minimo rumore, nessuna rotazione, alta qualità."""
    # Solo leggero rumore gaussiano
    arr = np.array(img).astype(np.float32)
    noise = rng.gauss(0, 3)
    arr = np.clip(arr + np.random.normal(0, abs(noise) or 1, arr.shape), 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _apply_medium(img: Image.Image, rng: random.Random) -> Image.Image:
    """Blur leggero + rotazione ±5° + rumore moderato."""
    # Rotazione
    angle = rng.uniform(-5, 5)
    img = img.rotate(angle, fillcolor=(245, 245, 245), expand=False)

    # Leggero blur
    blur_radius = rng.uniform(0.8, 1.8)
    img = img.filter(ImageFilter.GaussianBlur(blur_radius))

    # Rumore
    arr = np.array(img).astype(np.float32)
    arr = np.clip(arr + np.random.normal(0, 12, arr.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Contrasto leggermente ridotto
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.95))
    return img


def _apply_hard(img: Image.Image, rng: random.Random) -> Image.Image:
    """Forte blur + rotazione ±15° + bassa luminosità + contrasto ridotto + prospettiva."""
    # Rotazione accentuata
    angle = rng.uniform(-15, 15)
    img = img.rotate(angle, fillcolor=(220, 215, 210), expand=False)

    # Blur forte
    blur_radius = rng.uniform(2.0, 4.0)
    img = img.filter(ImageFilter.GaussianBlur(blur_radius))

    # Rumore elevato
    arr = np.array(img).astype(np.float32)
    arr = np.clip(arr + np.random.normal(0, 28, arr.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Bassa luce: schiaccia verso il basso la luminosità
    brightness = rng.uniform(0.45, 0.70)
    img = ImageEnhance.Brightness(img).enhance(brightness)

    # Contrasto ridotto (inchiostro sbiadito)
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.50, 0.75))

    # Leggera distorsione prospettica via resize asimmetrico
    w, h = img.size
    skew = rng.uniform(0.92, 0.98)
    img = img.resize((int(w * skew), h), Image.LANCZOS)
    img = img.resize((w, h), Image.LANCZOS)

    return img


def generate_receipt_image(receipt: Receipt, seed: int) -> Image.Image:
    rng = random.Random(seed)
    np.random.seed(seed)

    img = _render_receipt_base(receipt)
    if receipt.difficulty == "easy":
        return _apply_easy(img, rng)
    elif receipt.difficulty == "medium":
        return _apply_medium(img, rng)
    else:
        return _apply_hard(img, rng)


# ---------------------------------------------------------------------------
# PREPROCESSING VARIANTI
# ---------------------------------------------------------------------------

def preprocess_baseline(img: Image.Image) -> Image.Image:
    """Pipeline attuale da ocr_client.py — invariata."""
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    if img.width < 800:
        scale = 800 / img.width
        img = img.resize((800, int(img.height * scale)), Image.LANCZOS)
    return img


def preprocess_deskew(img: Image.Image) -> Image.Image:
    """Stima angolo di rotazione e raddrizza + upscale 1200px."""
    img = img.convert("L")

    # Stima angolo via moments su immagine binarizzata
    arr = np.array(img)
    binary = (arr < 128).astype(np.uint8)
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) > 100:
        angle = _estimate_skew(coords)
        if abs(angle) > 0.5:
            img = img.rotate(angle, fillcolor=255, expand=False)

    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.filter(ImageFilter.SHARPEN)
    # Upscale maggiore
    target = 1200
    if img.width < target:
        scale = target / img.width
        img = img.resize((target, int(img.height * scale)), Image.LANCZOS)
    return img


def _estimate_skew(coords: np.ndarray) -> float:
    """Stima l'angolo di skew con PCA sulle coordinate dei pixel scuri."""
    mean = coords.mean(axis=0)
    centered = coords - mean
    cov = np.cov(centered.T)
    if cov.ndim < 2:
        return 0.0
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    principal = eigenvectors[:, np.argmax(eigenvalues)]
    angle_rad = math.atan2(principal[0], principal[1])
    angle_deg = math.degrees(angle_rad)
    # Limita a ±45° per evitare correzioni assurde
    if abs(angle_deg) > 45:
        angle_deg = 0.0
    return -angle_deg


def preprocess_otsu(img: Image.Image) -> Image.Image:
    """Binarizzazione Otsu: soglia adattiva per testo sbiadito."""
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(1.5)

    # Calcola soglia Otsu manualmente (senza OpenCV)
    arr = np.array(img)
    hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
    total = arr.size
    sum_all = np.dot(np.arange(256), hist)
    sum_b, w_b, max_var, threshold = 0.0, 0, 0.0, 128

    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        mean_b = sum_b / w_b
        mean_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (mean_b - mean_f) ** 2
        if var > max_var:
            max_var = var
            threshold = t

    # Binarizza
    binary = arr > threshold
    result = np.where(binary, 255, 0).astype(np.uint8)
    img = Image.fromarray(result)

    if img.width < 800:
        scale = 800 / img.width
        img = img.resize((800, int(img.height * scale)), Image.LANCZOS)
    return img


# ---------------------------------------------------------------------------
# OCR RUNNER
# ---------------------------------------------------------------------------

_MIN_CHARS = 10


def run_ocr(img: Image.Image, psm: int = 3) -> tuple[str, float]:
    """Esegue OCR Tesseract e restituisce (testo, ms)."""
    config = f"--psm {psm} --oem 1"
    t0 = time.perf_counter()
    raw = pytesseract.image_to_string(img, lang="ita", config=config)
    elapsed = (time.perf_counter() - t0) * 1000
    # Pulizia base identica a ocr_client._clean
    import re
    lines = raw.splitlines()
    filtered = [l for l in lines if re.search(r"[a-zA-Z0-9€,.]", l)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(filtered)).strip()
    return cleaned, elapsed


# ---------------------------------------------------------------------------
# SCORING PER SINGOLO SCONTRINO
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    receipt: Receipt
    texts: dict[str, str]        # variante → testo OCR estratto
    times: dict[str, float]      # variante → ms
    scores: dict[str, float]     # variante → 0-1
    details: dict[str, dict]     # variante → {found: [...], missed: [...]}


def _score_ocr(text: str, receipt: Receipt) -> tuple[float, dict]:
    """Calcola accuracy: quante keyword note sono state trovate nel testo OCR."""
    import re
    text_lower = text.lower()

    targets: list[str] = []
    # Nome negozio
    targets.append(receipt.store.lower().split()[0])    # prima parola del nome
    # Totale (solo cifre significative, non i centesimi se ambigui)
    total_main = receipt.total.split(".")[0]             # es. "87" da "87.43"
    targets.append(total_main)
    # Ogni voce: prima parola del nome + prezzo
    for name, price in receipt.items:
        targets.append(name.split()[0].lower())
        price_main = price.split(".")[0]
        if len(price_main) >= 2:                         # prezzi tipo "0.99" → skip cifra unica
            targets.append(price_main)

    found = [t for t in targets if t in text_lower or t in text]
    missed = [t for t in targets if t not in text_lower and t not in text]

    score = len(found) / len(targets) if targets else 0.0
    return score, {"found": found, "missed": missed, "total_targets": len(targets)}


# ---------------------------------------------------------------------------
# VARIANTI DI BENCHMARK
# ---------------------------------------------------------------------------

_VARIANTS: dict[str, tuple[Callable, int]] = {
    "Baseline": (preprocess_baseline, 3),
    "PSM-6":    (preprocess_baseline, 6),
    "Deskew":   (preprocess_deskew,   6),
    "Otsu":     (preprocess_otsu,     6),
}


def run_benchmark(
    receipts: list[Receipt],
    save_images: bool = False,
    images_dir: str = "",
) -> list[CaseResult]:
    results: list[CaseResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Elaborazione {len(receipts)} scontrini × {len(_VARIANTS)} varianti...",
            total=len(receipts) * len(_VARIANTS),
        )

        for i, receipt in enumerate(receipts):
            img_orig = generate_receipt_image(receipt, seed=i * 7 + 42)

            if save_images and images_dir:
                save_path = os.path.join(images_dir, f"{i:02d}_{receipt.difficulty}_{receipt.label.replace(' ', '_')}.png")
                img_orig.save(save_path)

            texts, times, scores, details = {}, {}, {}, {}

            for variant_name, (preprocess_fn, psm) in _VARIANTS.items():
                try:
                    processed = preprocess_fn(img_orig.copy())
                    text, ms = run_ocr(processed, psm=psm)
                    score, det = _score_ocr(text, receipt)
                except Exception as e:
                    text, ms, score, det = f"[ERRORE: {e}]", 0.0, 0.0, {"found": [], "missed": [], "total_targets": 0}

                texts[variant_name] = text
                times[variant_name] = ms
                scores[variant_name] = score
                details[variant_name] = det
                progress.advance(task)

            results.append(CaseResult(receipt, texts, times, scores, details))

    return results


# ---------------------------------------------------------------------------
# OUTPUT CONSOLE
# ---------------------------------------------------------------------------

def _score_color(s: float) -> str:
    if s >= 0.80:
        return "green"
    if s >= 0.50:
        return "yellow"
    return "red"


def print_summary_table(results: list[CaseResult]) -> None:
    console.print(Rule("[bold cyan]RISULTATI PER SCONTRINO[/bold cyan]"))

    table = Table(
        title="Accuracy OCR (keyword trovate / keyword attese)",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold white on dark_blue",
    )
    table.add_column("#",           style="dim",   width=3)
    table.add_column("Negozio",     style="white", min_width=16)
    table.add_column("Label",       style="dim",   min_width=22)
    table.add_column("Diff",        justify="center", min_width=8)
    for v in _VARIANTS:
        table.add_column(v, justify="center", min_width=10)

    for i, r in enumerate(results):
        diff_color = {"easy": "green", "medium": "yellow", "hard": "red"}[r.receipt.difficulty]
        row = [
            str(i + 1),
            r.receipt.store[:16],
            r.receipt.label[:22],
            f"[{diff_color}]{r.receipt.difficulty}[/{diff_color}]",
        ]
        for v in _VARIANTS:
            s = r.scores[v]
            c = _score_color(s)
            row.append(f"[{c}]{s:.0%}[/{c}]")
        table.add_row(*row)

    console.print(table)
    console.print()


def print_stats_by_difficulty(results: list[CaseResult]) -> None:
    console.print(Rule("[bold cyan]STATISTICHE PER DIFFICOLTÀ[/bold cyan]"))

    for diff in ("easy", "medium", "hard"):
        subset = [r for r in results if r.receipt.difficulty == diff]
        if not subset:
            continue

        diff_color = {"easy": "green", "medium": "yellow", "hard": "red"}[diff]
        stats_table = Table(
            title=f"[{diff_color}]{diff.upper()}[/{diff_color}]  ({len(subset)} scontrini)",
            box=box.SIMPLE_HEAD,
            header_style="bold",
        )
        stats_table.add_column("Variante",       style="bold",  min_width=14)
        stats_table.add_column("Acc. media",     justify="center", min_width=12)
        stats_table.add_column("≥80% (pass)",    justify="center", min_width=12)
        stats_table.add_column("<50% (fail)",    justify="center", min_width=12)
        stats_table.add_column("Tempo medio ms", justify="center", min_width=16)

        for v in _VARIANTS:
            scores = [r.scores[v] for r in subset]
            times  = [r.times[v]  for r in subset]
            avg    = sum(scores) / len(scores)
            passes = sum(1 for s in scores if s >= 0.80)
            fails  = sum(1 for s in scores if s < 0.50)
            avg_t  = sum(times) / len(times)
            c = _score_color(avg)
            stats_table.add_row(
                v,
                f"[{c}]{avg:.1%}[/{c}]",
                f"[green]{passes}/{len(subset)}[/green]",
                f"[red]{fails}/{len(subset)}[/red]",
                f"{avg_t:.0f}ms",
            )

        console.print(stats_table)
        console.print()


def print_global_winner(results: list[CaseResult]) -> None:
    console.print(Rule("[bold cyan]RIEPILOGO GLOBALE[/bold cyan]"))

    global_table = Table(
        title=f"Tutte le difficoltà ({len(results)} scontrini)",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
    )
    global_table.add_column("Variante",       style="bold",  min_width=14)
    global_table.add_column("Acc. media",     justify="center", min_width=12)
    global_table.add_column("Easy avg",       justify="center", min_width=10)
    global_table.add_column("Medium avg",     justify="center", min_width=10)
    global_table.add_column("Hard avg",       justify="center", min_width=10)
    global_table.add_column("Pass rate ≥80%", justify="center", min_width=14)
    global_table.add_column("Tempo totale",   justify="center", min_width=14)

    best_variant = ""
    best_avg = -1.0

    for v in _VARIANTS:
        all_scores = [r.scores[v] for r in results]
        avg = sum(all_scores) / len(all_scores)

        by_diff = {}
        for diff in ("easy", "medium", "hard"):
            sub = [r.scores[v] for r in results if r.receipt.difficulty == diff]
            by_diff[diff] = sum(sub) / len(sub) if sub else 0.0

        passes = sum(1 for s in all_scores if s >= 0.80)
        total_t = sum(r.times[v] for r in results) / 1000  # secondi
        c = _score_color(avg)

        global_table.add_row(
            v,
            f"[{c}][bold]{avg:.1%}[/bold][/{c}]",
            f"[green]{by_diff['easy']:.1%}[/green]",
            f"[yellow]{by_diff['medium']:.1%}[/yellow]",
            f"[red]{by_diff['hard']:.1%}[/red]",
            f"{passes}/{len(results)}",
            f"{total_t:.1f}s",
        )

        if avg > best_avg:
            best_avg = avg
            best_variant = v

    console.print(global_table)
    console.print()
    console.print(
        f"[bold green]Variante migliore: {best_variant}[/bold green]  "
        f"(accuracy media: [bold]{best_avg:.1%}[/bold])"
    )
    console.print()


def print_failures(results: list[CaseResult], best_variant: str = "Baseline") -> None:
    """Mostra i casi con accuracy < 50% per la variante baseline."""
    failures = [(i, r) for i, r in enumerate(results) if r.scores[best_variant] < 0.50]
    if not failures:
        console.print(f"[green]Nessun fallimento (<50%) per variante {best_variant}![/green]")
        return

    console.print(Rule(f"[bold red]FALLIMENTI {best_variant} (accuracy < 50%)[/bold red]"))
    for i, r in failures:
        missed = r.details[best_variant].get("missed", [])
        score = r.scores[best_variant]
        panel = Panel(
            f"[dim]Mancanti:[/dim] {', '.join(missed[:10])}\n\n"
            f"[dim]Testo OCR (prime 300 chars):[/dim]\n{r.texts[best_variant][:300]}",
            title=f"#{i+1} [{r.receipt.difficulty}] {r.receipt.store} — {r.receipt.label}  "
                  f"[red]{score:.0%}[/red]",
            border_style="red",
        )
        console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark OCR su scontrini sintetici")
    parser.add_argument("--save-images",  action="store_true", help="Salva immagini generate in logs/ocr_images/")
    parser.add_argument("--difficulty",   choices=["easy", "medium", "hard"], help="Testa solo una difficoltà")
    parser.add_argument("--show-failures", action="store_true", help="Mostra dettaglio fallimenti baseline")
    args = parser.parse_args()

    console.print(Rule("[bold magenta]BENCHMARK OCR — Scontrini Sintetici[/bold magenta]"))
    console.print("[dim]Genera 30 scontrini con PIL, testa 4 varianti preprocessing Tesseract 5[/dim]")
    console.print()

    receipts = _RECEIPTS
    if args.difficulty:
        receipts = [r for r in _RECEIPTS if r.difficulty == args.difficulty]
        console.print(f"[yellow]Filtro difficoltà: [bold]{args.difficulty}[/bold] ({len(receipts)} scontrini)[/yellow]")

    images_dir = ""
    if args.save_images:
        images_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "ocr_images"
        )
        os.makedirs(images_dir, exist_ok=True)
        console.print(f"[dim]Immagini salvate in: {images_dir}[/dim]")

    console.print(f"Scontrini: [bold]{len(receipts)}[/bold]  |  "
                  f"Varianti preprocessing: [bold]{len(_VARIANTS)}[/bold]  |  "
                  f"Tesseract: [bold]5.3.4[/bold]")
    console.print()

    results = run_benchmark(receipts, save_images=args.save_images, images_dir=images_dir)

    print_summary_table(results)
    print_stats_by_difficulty(results)
    print_global_winner(results)

    if args.show_failures:
        print_failures(results, best_variant="Baseline")

    # Salva HTML
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = os.path.join(output_dir, f"benchmark_ocr_{ts}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(console.export_html())
    console.print(f"[green]Report HTML salvato:[/green] {html_path}")
    console.print(Rule("[bold green]BENCHMARK COMPLETATO[/bold green]"))


if __name__ == "__main__":
    main()
