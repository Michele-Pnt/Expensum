"""
scripts/colab/build_notebook.py — Genera gemma_selfhosted_benchmark.ipynb.

Non è pensato per girare in produzione: è un generatore one-shot che assembla il
notebook Colab a partire dai prompt/dati REALI del progetto (system prompt di
expense_parser.py, categorie di workspace_bootstrapper.py, template di
mistral_client.py, prompt weekly/monthly già generati dai builder di produzione),
cosi' il notebook resta sincronizzato con la codebase invece di essere scritto a mano
con dati potenzialmente disallineati.

Uso:
  python scripts/colab/build_notebook.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.expense_parser import _SYSTEM_PROMPT
from src.workspace_bootstrapper import DEFAULT_CATEGORIES
from src.mistral_client import _WEEKLY_PLAN_PROMPT_TEMPLATE, _MONTHLY_PLAN_PROMPT_TEMPLATE

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = "/tmp/claude-1000/-home-michele-Desktop-Finance-Agents/4e9687a7-2c6c-4af4-a132-0b9cbe827992/scratchpad"

with open(os.path.join(SCRATCH, "weekly_prompt.txt"), encoding="utf-8") as f:
    WEEKLY_PROMPT_DATA = f.read()
with open(os.path.join(SCRATCH, "monthly_prompt.txt"), encoding="utf-8") as f:
    MONTHLY_PROMPT_DATA = f.read()

# Stessi identici casi di scripts/benchmark_parsing_text.py — copiati qui (non importati)
# perché il notebook deve essere autosufficiente su Colab, senza il resto del repo.
TEXT_CASES = [
    {"msg": "pizza 15", "type": "expense", "amount": 15.0, "category": "Ristorante"},
    {"msg": "benzina 40 euro", "type": "expense", "amount": 40.0, "category": "Carburante"},
    {"msg": "affitto", "type": "expense", "amount": None, "category": "Affitto"},
    {"msg": "netflix", "type": "expense", "amount": None, "category": None},
    {"msg": "ieri sera mangiato fuori tipo 40 con i ragazzi", "type": "expense", "amount": 40.0,
     "category": "Ristorante", "date": "2026-04-09"},
    {"msg": "ho preso caffè e cornetto stamattina 2.70", "type": "expense", "amount": 2.70, "category": "Bar"},
    {"msg": "spesa esselunga ieri circa 90", "type": "expense", "amount": 90.0,
     "category": "Supermercato", "date": "2026-04-09"},
    {"msg": "cento euro di spesa", "type": "expense", "amount": 100.0, "category": "Supermercato"},
    {"msg": "100 euro", "type": None},
    {"msg": "arrivato lo stipendio 1800", "type": "income", "amount": 1800.0, "income_type": "Stipendio"},
    {"msg": "bonus 300€", "type": "income", "amount": 300.0, "income_type": "Bonus"},
    {"msg": "mi hanno rimborsato il viaggio 120", "type": "income", "amount": 120.0, "income_type": "Rimborso"},
    {"msg": "regalo di compleanno 50 euro dalla nonna", "type": "income", "amount": 50.0, "income_type": "Regalo"},
    {"msg": "sposta 100 euro dal conto corrente al conto risparmio", "type": "transfer", "amount": 100.0,
     "from_account": "conto corrente", "to_account": "conto risparmio"},
    {"msg": "giroconto di 50€ da Revolut a Fineco", "type": "transfer", "amount": 50.0,
     "from_account": "Revolut", "to_account": "Fineco"},
    {"msg": "3 settimane fa ho pagato 80 euro di dentista", "type": "expense", "amount": 80.0,
     "category": "Medicina", "date": "2026-03-20"},
    {"msg": "il mese scorso bolletta della luce 95 euro", "type": "expense", "amount": 95.0,
     "category": "Bollette luce", "date": "2026-03-01"},
    {"msg": "ok grazie", "type": None},
    {"msg": "domani devo pagare l'affitto", "type": "expense", "amount": None,
     "category": "Affitto", "date": "2026-04-11"},
    {"msg": "ho speso 10 euro per il pranzo, 20 di benzina e 5 di caffè ieri", "type": "multi",
     "count": 3, "date": "2026-04-09"},
    {"msg": "oggi 15 euro di spesa e ieri ho ricevuto un rimborso di 50 euro", "type": "multi", "count": 2},
    {"msg": "farmacia ieri 23.50", "type": "expense", "amount": 23.50, "category": "Farmacia", "date": "2026-04-09"},
    {"msg": "ricarica telefono 15", "type": "expense", "amount": 15.0, "category": "Telefono"},
]

# Scontrini sintetici per il task foto (vision) — ground truth nota.
PHOTO_CASES = [
    {"store": "ESSELUNGA", "items": [("Pane integrale", "1.29"), ("Latte fresco", "1.45"), ("Uova x6", "2.89")],
     "total": "5.63", "date": "15/04/2026", "category": "Supermercato"},
    {"store": "SHELL", "items": [("Benzina 30L", "51.90"), ("Acqua 0.5L", "1.50")],
     "total": "53.40", "date": "12/04/2026", "category": "Carburante"},
    {"store": "FARMACIA SANT'ANNA", "items": [("Aspirina 20cpr", "3.50"), ("Vitamina C", "6.90")],
     "total": "10.40", "date": "10/04/2026", "category": "Farmacia"},
    {"store": "TRATTORIA DA LUIGI", "items": [("Tagliatelle al ragu'", "12.00"), ("Vino della casa", "4.50"),
                                                ("Coperto", "2.00")],
     "total": "18.50", "date": "08/04/2026", "category": "Ristorante"},
    {"store": "ZARA", "items": [("T-shirt bianca S", "17.95"), ("Jeans slim 32", "39.95")],
     "total": "57.90", "date": "05/04/2026", "category": "Abbigliamento"},
    {"store": "AUTOGRILL", "items": [("Panino prosciutto", "5.50"), ("Caffe' doppio", "2.10")],
     "total": "7.60", "date": "01/04/2026", "category": "Bar"},
]

# Frasi vocali sintetiche (gTTS) per il task audio — ground truth nota.
AUDIO_CASES = [
    {"text": "ho speso diciotto euro per il pranzo al lavoro oggi",
     "type": "expense", "amount": 18.0, "category": "Ristorante"},
    {"text": "ho ricevuto un rimborso di ventiquattro euro dal collega",
     "type": "income", "amount": 24.0, "income_type": "Rimborso"},
    {"text": "trentacinque euro di benzina ieri",
     "type": "expense", "amount": 35.0, "category": "Carburante"},
    {"text": "arrivato lo stipendio di milleottocento euro",
     "type": "income", "amount": 1800.0, "income_type": "Stipendio"},
    {"text": "dodici euro e cinquanta di farmacia",
     "type": "expense", "amount": 12.50, "category": "Farmacia"},
    {"text": "sposta cento euro dal conto corrente al conto risparmio",
     "type": "transfer", "amount": 100.0, "from_account": "conto corrente", "to_account": "conto risparmio"},
]


def build_notebook() -> dict:
    cells = []

    def md(src: str):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)})

    def code(src: str):
        cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                       "source": src.splitlines(keepends=True)})

    md("""# Benchmark self-hosted: gemma3n vs gemma2:2b — Expensum

Notebook autosufficiente (nessuna dipendenza dal repo privato) per testare i modelli
self-hosted su GPU gratuita Colab, sui 4 task reali del bot: **parsing testo, report
settimanale/mensile, parsing foto (vision), parsing audio**.

**Prerequisiti prima di eseguire:**
1. `Runtime -> Change runtime type -> T4 GPU`
2. Accetta la licenza Gemma su Hugging Face per **entrambi** i modelli (una volta sola,
   serve un account HF): https://huggingface.co/google/gemma-3n-e2b-it e
   https://huggingface.co/google/gemma-2-2b-it
3. Esegui le celle in ordine. In fondo trovi il download del file
   `gemma_colab_results.json` — dallo a Claude per lo scoring finale (fatto in locale
   con le stesse funzioni usate per Mistral, cosi' il confronto resta omogeneo).

Ogni cella salva i risultati **grezzi** (testo generato dal modello, non ancora
punteggiato) — lo scoring/confronto con Mistral avviene fuori da qui.""")

    code("""!pip install -q -U "transformers>=4.53.0" accelerate gTTS pillow bitsandbytes""")

    code("""from huggingface_hub import notebook_login
notebook_login()  # serve un token HF con accesso accettato alla licenza Gemma""")

    code("""import torch, json, time, gc, os
from datetime import date

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print("GPU disponibile:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "—")

RESULTS = {"text_parsing": {}, "reports": {}, "photo": {}, "audio": {}}

def free_model(*names: str):
    \"\"\"Libera VRAM per davvero: cancella i nomi dal namespace GLOBALE del notebook,
    non variabili locali (del o su un parametro locale NON tocca l'oggetto originale
    referenziato altrove — la VRAM resterebbe occupata e il modello successivo
    verrebbe silenziosamente spezzato su CPU da device_map="auto").\"\"\"
    for name in names:
        if name in globals():
            del globals()[name]
    gc.collect()
    torch.cuda.empty_cache()
    print(f"VRAM allocata dopo pulizia: {torch.cuda.memory_allocated() / 1e9:.2f} GB")""")

    # repr(), non json.dumps(): questi valori vengono incollati come CODICE PYTHON
    # nelle celle del notebook, non come JSON — json.dumps produrrebbe "null"/"true"
    # (validi in JSON, NON validi come letterali Python: causa NameError su None).
    system_prompt_json = repr(_SYSTEM_PROMPT)
    categories_json = repr(DEFAULT_CATEGORIES)
    cases_json = repr(TEXT_CASES)
    photo_cases_json = repr(PHOTO_CASES)
    audio_cases_json = repr(AUDIO_CASES)
    weekly_template_json = repr(_WEEKLY_PLAN_PROMPT_TEMPLATE)
    monthly_template_json = repr(_MONTHLY_PLAN_PROMPT_TEMPLATE)
    weekly_data_json = repr(WEEKLY_PROMPT_DATA)
    monthly_data_json = repr(MONTHLY_PROMPT_DATA)

    md("""## Costanti — copiate 1:1 dal codice di produzione

`SYSTEM_PROMPT` e `CATEGORIES` vengono da `src/expense_parser.py` e
`src/workspace_bootstrapper.py`. `WEEKLY_PROMPT_DATA`/`MONTHLY_PROMPT_DATA` sono
l'output GIA' CALCOLATO da `WeeklyPlanBuilder`/`MonthlyPlanBuilder` sugli stessi dati
mock usati per il test locale Mistral — così il confronto è sullo stesso identico
input, non ricalcolato qui.""")

    code(f"""SYSTEM_PROMPT = {system_prompt_json}
CATEGORIES = {categories_json}
TEXT_CASES = {cases_json}
PHOTO_CASES = {photo_cases_json}
AUDIO_CASES = {audio_cases_json}
WEEKLY_TEMPLATE = {weekly_template_json}
MONTHLY_TEMPLATE = {monthly_template_json}
WEEKLY_PROMPT_DATA = {weekly_data_json}
MONTHLY_PROMPT_DATA = {monthly_data_json}
WEEK_LABEL = "16/02 → 22/02"
MONTH_LABEL = "Marzo 2026"

def build_user_prompt(message: str) -> str:
    cats_str = ", ".join(CATEGORIES)
    return f'Data di oggi: 2026-04-10\\nCategorie disponibili: [{{cats_str}}]\\n\\nMessaggio dell\\'utente: "{{message}}"'
""")

    md("""## PARTE 1 — gemma2:2b (solo testo: parsing testo + report)

`gemma2:2b` non supporta immagini/audio: partecipa solo ai due task testuali.""")

    code("""from transformers import AutoTokenizer, AutoModelForCausalLM

GEMMA2_ID = "google/gemma-2-2b-it"
g2_tok = AutoTokenizer.from_pretrained(GEMMA2_ID)
g2_model = AutoModelForCausalLM.from_pretrained(GEMMA2_ID, torch_dtype=torch.bfloat16).to(DEVICE).eval()

def gemma2_chat(system: str | None, user: str, max_new_tokens: int = 1024) -> tuple[str, float]:
    msgs = []
    # gemma2 non supporta il ruolo "system" nel chat template ufficiale: lo prependiamo al messaggio utente
    content = f"{system}\\n\\n{user}" if system else user
    msgs.append({"role": "user", "content": content})
    inputs = g2_tok.apply_chat_template(
        msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True,
    ).to(g2_model.device)
    t0 = time.time()
    with torch.inference_mode():
        out = g2_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    elapsed = time.time() - t0
    text = g2_tok.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    return text, elapsed""")

    code("""# Parsing testo — gemma2:2b
RESULTS["text_parsing"]["gemma2:2b"] = []
for case in TEXT_CASES:
    user_prompt = build_user_prompt(case["msg"])
    text, elapsed = gemma2_chat(SYSTEM_PROMPT, user_prompt, max_new_tokens=512)
    RESULTS["text_parsing"]["gemma2:2b"].append({"msg": case["msg"], "raw_output": text, "elapsed_s": elapsed})
    print(f"[{elapsed:5.1f}s] {case['msg'][:40]:40s} -> {text[:80]}")
""")

    code("""# Report settimanale + mensile — gemma2:2b
weekly_prompt = WEEKLY_TEMPLATE.format(plan_data=WEEKLY_PROMPT_DATA, week_label=WEEK_LABEL)
monthly_prompt = MONTHLY_TEMPLATE.format(plan_data=MONTHLY_PROMPT_DATA, month_label=MONTH_LABEL)

text, elapsed = gemma2_chat(None, weekly_prompt, max_new_tokens=2048)
RESULTS["reports"]["gemma2:2b_weekly"] = {"raw_output": text, "elapsed_s": elapsed}
print(f"weekly [{elapsed:.1f}s]:\\n{text[:500]}")

text, elapsed = gemma2_chat(None, monthly_prompt, max_new_tokens=2048)
RESULTS["reports"]["gemma2:2b_monthly"] = {"raw_output": text, "elapsed_s": elapsed}
print(f"monthly [{elapsed:.1f}s]:\\n{text[:500]}")
""")

    code("""# Libera VRAM prima di caricare gemma3n
free_model("g2_model", "g2_tok")""")

    md("""## PARTE 2 — gemma3n:e2b (multimodale: testo + report + foto + audio)

`e2b` è la variante "on-device" (footprint ridotto) — coerente con la domanda
originale "gira su un telefono di fascia bassa?". Se vuoi il tetto massimo di qualità,
cambia `GEMMA3N_ID` in `google/gemma-3n-e4b-it` (più pesante, ~8B effettivi) e rilancia
solo questa sezione.""")

    code("""from transformers import AutoProcessor, Gemma3nForConditionalGeneration

GEMMA3N_ID = "google/gemma-3n-e2b-it"
g3_proc = AutoProcessor.from_pretrained(GEMMA3N_ID)
g3_model = Gemma3nForConditionalGeneration.from_pretrained(GEMMA3N_ID, torch_dtype=torch.bfloat16).to(DEVICE).eval()

def gemma3n_chat(content_blocks: list[dict], system: str | None = None, max_new_tokens: int = 1024,
                  _debug_keys: bool = False) -> tuple[str, float]:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": [{"type": "text", "text": system}]})
    msgs.append({"role": "user", "content": content_blocks})
    inputs = g3_proc.apply_chat_template(
        msgs, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt",
    ).to(g3_model.device)
    if _debug_keys:
        # Sanity check: se manca una chiave tipo "input_features"/"audio_..." qui,
        # il contenuto audio/immagine NON è stato agganciato dal processor — è stato
        # silenziosamente ignorato, e il modello risponde solo al testo (bug capitato
        # con la prima versione di questo notebook: verificare SEMPRE prima di lanciare
        # un intero batch, non dopo).
        print("  [debug] chiavi inputs:", list(inputs.keys()))
    t0 = time.time()
    with torch.inference_mode():
        out = g3_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    elapsed = time.time() - t0
    text = g3_proc.decode(out[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    return text, elapsed""")

    code("""# Parsing testo — gemma3n:e2b
RESULTS["text_parsing"]["gemma3n:e2b"] = []
for case in TEXT_CASES:
    user_prompt = build_user_prompt(case["msg"])
    text, elapsed = gemma3n_chat([{"type": "text", "text": user_prompt}], system=SYSTEM_PROMPT, max_new_tokens=512)
    RESULTS["text_parsing"]["gemma3n:e2b"].append({"msg": case["msg"], "raw_output": text, "elapsed_s": elapsed})
    print(f"[{elapsed:5.1f}s] {case['msg'][:40]:40s} -> {text[:80]}")
""")

    code("""# Report settimanale + mensile — gemma3n:e2b
text, elapsed = gemma3n_chat([{"type": "text", "text": weekly_prompt}], max_new_tokens=2048)
RESULTS["reports"]["gemma3n:e2b_weekly"] = {"raw_output": text, "elapsed_s": elapsed}
print(f"weekly [{elapsed:.1f}s]:\\n{text[:500]}")

text, elapsed = gemma3n_chat([{"type": "text", "text": monthly_prompt}], max_new_tokens=2048)
RESULTS["reports"]["gemma3n:e2b_monthly"] = {"raw_output": text, "elapsed_s": elapsed}
print(f"monthly [{elapsed:.1f}s]:\\n{text[:500]}")
""")

    md("""### Foto — genera scontrini sintetici e chiedi a gemma3n il JSON transazione completo

Un solo hop: immagine -> JSON strutturato (stesso schema di `expense_parser.py`),
niente OCR intermedio — è il modo naturale di usare un modello multimodale, ed è la
differenza che vogliamo misurare rispetto alla pipeline attuale (Tesseract + Mistral).""")

    code("""from PIL import Image, ImageDraw, ImageFont

# Font di sistema a dimensione leggibile — ImageFont.load_default() genera un
# bitmap font minuscolo (~8px), illeggibile anche per un umano allo zoom nativo:
# nel primo giro di test gemma3n non ha MAI letto correttamente la data dello
# scontrino, sempre sostituita con la data odierna del prompt — probabile causa,
# non necessariamente un limite del modello. Font TrueType a 28px + upscale 2x
# per dare al vision encoder margine sufficiente a distinguere i caratteri.
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise RuntimeError("Nessun font TrueType di sistema trovato — impossibile generare scontrini leggibili")

def render_receipt(case: dict) -> Image.Image:
    font = _load_font(28)
    font_bold = _load_font(30)
    lines = [(case["store"].upper(), True), ("-" * 32, False), ("SCONTRINO FISCALE", True), ("-" * 32, False)]
    for name, price in case["items"]:
        lines.append((f"{name:<22}{price:>8}", False))
    lines.append(("-" * 32, False))
    lines.append((f"TOTALE EUR{case['total']:>20}", True))
    lines.append(("-" * 32, False))
    lines.append((case["date"], False))
    line_height = 38
    img = Image.new("RGB", (720, len(lines) * line_height + 40), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 20
    for text_line, bold in lines:
        draw.text((20, y), text_line, fill=(10, 10, 10), font=font_bold if bold else font)
        y += line_height
    return img

PHOTO_PROMPT = (
    SYSTEM_PROMPT
    + '\\n\\nEstrai la transazione da questa foto di scontrino. '
    + f'Data di oggi: 2026-04-10\\nCategorie disponibili: [{", ".join(CATEGORIES)}]'
)

RESULTS["photo"]["gemma3n:e2b"] = []
for i, case in enumerate(PHOTO_CASES):
    img = render_receipt(case)
    if i == 0:
        display(img)  # controllo visivo: verifica TU STESSO che sia leggibile prima di lanciare tutto il batch
    text, elapsed = gemma3n_chat(
        [{"type": "image", "image": img}, {"type": "text", "text": PHOTO_PROMPT}],
        max_new_tokens=512, _debug_keys=(i == 0),
    )
    RESULTS["photo"]["gemma3n:e2b"].append({
        "ground_truth": case, "raw_output": text, "elapsed_s": elapsed,
    })
    print(f"[{elapsed:5.1f}s] {case['store']:25s} -> {text[:100]}")
""")

    md("""### Audio — genera frasi vocali sintetiche (gTTS) e chiedi a gemma3n il JSON transazione completo""")

    code("""!pip install -q soundfile librosa

from gtts import gTTS
import librosa
import soundfile as sf

AUDIO_PROMPT = (
    SYSTEM_PROMPT
    + '\\n\\nTrascrivi ed estrai la transazione da questo audio. '
    + f'Data di oggi: 2026-04-10\\nCategorie disponibili: [{", ".join(CATEGORIES)}]'
)

# IMPORTANTE: passiamo un PERCORSO FILE ("path"), non un array numpy pre-caricato.
# Nel primo giro, un array grezzo passato sotto {"type": "audio", "audio": wav} è
# stato silenziosamente ignorato dal processor (5 risposte su 6 identiche, il
# modello rispondeva solo al testo) — passare il path lascia che sia il processor
# stesso a caricare/ricampionare l'audio nel formato che si aspetta internamente,
# stesso pattern documentato e funzionante per i video multimodali in transformers.
RESULTS["audio"]["gemma3n:e2b"] = []
for i, case in enumerate(AUDIO_CASES):
    mp3_path = f"/content/audio_{i}.mp3"
    wav_path = f"/content/audio_{i}.wav"
    gTTS(text=case["text"], lang="it").save(mp3_path)
    wav, sr = librosa.load(mp3_path, sr=16000)  # solo per convertire mp3 -> wav pulito
    sf.write(wav_path, wav, sr)

    text, elapsed = gemma3n_chat(
        [{"type": "audio", "path": wav_path}, {"type": "text", "text": AUDIO_PROMPT}],
        max_new_tokens=512, _debug_keys=(i == 0),
    )
    RESULTS["audio"]["gemma3n:e2b"].append({
        "ground_truth": case, "raw_output": text, "elapsed_s": elapsed,
    })
    print(f"[{elapsed:5.1f}s] {case['text'][:40]:40s} -> {text[:100]}")
""")

    md("""## Salva ed esporta i risultati

Scarica `gemma_colab_results.json` e dallo a Claude in sessione locale: verrà
punteggiato con le stesse funzioni di scoring usate per Mistral (nessun doppio
standard tra provider).""")

    code("""with open("/content/gemma_colab_results.json", "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)

from google.colab import files
files.download("/content/gemma_colab_results.json")
print("Fatto. Carica gemma_colab_results.json nella conversazione con Claude.")""")

    return {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


if __name__ == "__main__":
    nb = build_notebook()
    out_path = os.path.join(HERE, "gemma_selfhosted_benchmark.ipynb")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    print(f"Notebook scritto: {out_path} ({len(nb['cells'])} celle)")
