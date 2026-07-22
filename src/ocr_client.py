"""
src/ocr_client.py — Tesseract OCR wrapper per estrazione testo da foto scontrini.

Pipeline: immagine → preprocessing PIL → pytesseract (ita) → testo pulito →
estrazione allowlist (Art. 5(1)(c) GDPR — minimizzazione).

Allowlist invece di denylist: invece di enumerare cosa scartare (approccio fragile,
vedi il caso "scontrino parlante" farmacia sanzionato dal Garante Privacy), si tiene
SOLO ciò che il parser usa davvero — nome esercizio, data, importo totale — e si
scarta tutto il resto per default (righe articolo, indirizzo, telefono, IVA, numero
scontrino, ecc.). Nessun dato oltre questi 3 campi raggiunge mai l'LLM esterno o i log.
"""

import logging
import re

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger("financial_agent.ocr")

# Soglia minima di caratteri per considerare l'OCR riuscito
_MIN_TEXT_LENGTH = 10

# Etichette tipiche su scontrini italiani seguite dal nome di un terzo (cameriere,
# cassiere, cliente...) — dato personale non necessario alla categorizzazione della
# spesa (Art. 5(1)(c) GDPR: minimizzazione). Applicato come rete di sicurezza sulla
# riga nome-esercizio estratta dall'allowlist (difesa in profondità).
_PII_LABEL_RE = re.compile(
    r"^\s*(cameriere|operatore|cassiere|cassa\s*n?°?\s*\d*|cliente|servito\s+da|"
    r"addetto|venditore|referente|rif\.?\s*cliente|nome\s+cliente|tavolo\s*\d*)\s*[:\-].*$",
    re.IGNORECASE,
)

# Sequenze numeriche lunghe (carte fedeltà, codici fiscali, ultime cifre carta di
# pagamento) — non necessarie alla categorizzazione, vengono mascherate.
_LONG_DIGIT_RE = re.compile(r"\b\d[\d \-]{11,}\d\b")

# Data — formato italiano (gg/mm/aaaa, gg-mm-aa, gg.mm.aaaa) o ISO (aaaa-mm-gg).
_DATE_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2})\b")

# Importo totale — riga con etichetta nota (TOTALE, IMPORTO, DA PAGARE) seguita da un
# valore in formato prezzo. Cercato PRIMA del fallback su qualunque prezzo nel testo.
_TOTAL_LABEL_RE = re.compile(
    r"(totale\s*(?:eur|complessivo|euro)?|importo|da\s+pagare)\D{0,20}(\d{1,5}[.,]\d{2})",
    re.IGNORECASE,
)
# Fallback: qualunque valore in formato prezzo (usato se nessuna label matcha —
# si assume che il totale sia il valore più alto presente sullo scontrino).
_AMOUNT_ANY_RE = re.compile(r"\b(\d{1,5}[.,]\d{2})\b")


class OCRError(Exception):
    """Errore generico: impossibile leggere lo scontrino (foto illeggibile)."""


class OCRMerchantNotFoundError(OCRError):
    """Nome dell'esercizio non riconosciuto nel testo estratto."""


class OCRDateNotFoundError(OCRError):
    """Data non riconosciuta nel testo estratto."""


class OCRTotalNotFoundError(OCRError):
    """Importo totale non riconosciuto nel testo estratto."""


class OcrClient:
    """Wrapper Tesseract OCR con preprocessing immagine per scontrini."""

    def extract_text_from_image(self, image_path: str, chat_id: str = "unknown") -> str:
        """
        Estrae da un'immagine solo i campi necessari al parsing della spesa
        (nome esercizio, data, importo totale) usando Tesseract OCR (lingua italiana).

        Args:
            image_path: Percorso assoluto all'immagine (JPEG, PNG, ecc.)
            chat_id: Identificatore pseudonimo utente, solo per il logging strutturato.

        Returns:
            Testo minimizzato nel formato "Esercizio: ...\\nData: ...\\nTotale: ...".

        Raises:
            OCRError: testo OCR troppo corto, foto probabilmente illeggibile.
            OCRMerchantNotFoundError: nessun nome esercizio riconoscibile.
            OCRDateNotFoundError: nessuna data riconoscibile.
            OCRTotalNotFoundError: nessun importo totale riconoscibile.
        """
        logger.info(
            "ocr_started",
            extra={"domain": "usage", "event": "ocr_started", "chat_id": chat_id, "meta": {}},
        )

        img = Image.open(image_path)
        img = self._preprocess(img)

        raw_text = pytesseract.image_to_string(img, lang="ita")
        cleaned = self._clean(raw_text)

        if len(cleaned) < _MIN_TEXT_LENGTH:
            logger.warning(
                "ocr_text_too_short",
                extra={
                    "domain": "usage",
                    "event": "ocr_text_too_short",
                    "chat_id": chat_id,
                    "meta": {"length": len(cleaned)},
                },
            )
            raise OCRError("testo non leggibile")

        minimized = self._extract_relevant_fields(cleaned, chat_id)

        logger.info(
            "ocr_extraction_completed",
            extra={
                "domain": "usage",
                "event": "ocr_extraction_completed",
                "chat_id": chat_id,
                "meta": {"length": len(minimized)},
            },
        )
        return minimized

    def _preprocess(self, img: Image.Image) -> Image.Image:
        """Applica preprocessing per migliorare la leggibilità da parte di Tesseract."""
        # Scala di grigi — Tesseract lavora meglio in bianco e nero
        img = img.convert("L")

        # Aumento contrasto per scontrini sbiaditi o con illuminazione scarsa
        img = ImageEnhance.Contrast(img).enhance(2.0)

        # Leggero sharpening per testo sfocato
        img = img.filter(ImageFilter.SHARPEN)

        # Ridimensiona se l'immagine è troppo piccola (< 800px di larghezza)
        # Tesseract funziona meglio con immagini ad alta risoluzione
        if img.width < 800:
            scale = 800 / img.width
            new_size = (800, int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)

        return img

    def _clean(self, text: str) -> str:
        """Rimuove righe vuote eccessive e caratteri spazzatura dall'output Tesseract."""
        # Rimuovi righe composte solo da caratteri non-alfanumerici (es. "---", "|||")
        lines = text.splitlines()
        filtered = [line for line in lines if re.search(r"[a-zA-Z0-9€,.]", line)]

        # Collassa sequenze di righe vuote in una sola
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(filtered))
        return result.strip()

    def _extract_relevant_fields(self, text: str, chat_id: str) -> str:
        """
        Allowlist: estrae SOLO nome esercizio, data e importo totale dal testo OCR
        pulito, scartando tutto il resto (righe articolo, indirizzo, telefono, IVA,
        numero scontrino...). Solleva un'eccezione dedicata e logga in modo
        differenziato per ciascun campo mancante, così da poter distinguere in log
        (e in futuro nell'UX) "non ho trovato il totale" da "non ho trovato la data"
        da "non ho trovato l'esercizio", invece di un unico errore generico.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        merchant = self._extract_merchant(lines)
        if not merchant:
            self._log_field_missing("merchant", chat_id)
            raise OCRMerchantNotFoundError("nome esercizio non riconosciuto")

        date_str = self._extract_date(text)
        if not date_str:
            self._log_field_missing("date", chat_id)
            raise OCRDateNotFoundError("data non riconosciuta")

        total_str = self._extract_total(text)
        if not total_str:
            self._log_field_missing("total", chat_id)
            raise OCRTotalNotFoundError("importo totale non riconosciuto")

        # Difesa in profondità: anche il nome esercizio passa dal denylist, nel raro
        # caso in cui l'euristica catturi una riga con un'etichetta di terzi.
        merchant = self._redact_pii(merchant)

        return f"Esercizio: {merchant}\nData: {date_str}\nTotale: {total_str}"

    def _extract_merchant(self, lines: list[str]) -> str | None:
        """Euristica: il nome dell'esercizio è la prima riga non vuota "sensata"
        (su uno scontrino fiscale italiano standard è sempre in testa)."""
        for line in lines[:3]:
            candidate = line.strip(" -=*#")
            if len(candidate) >= 3 and re.search(r"[a-zA-Z]", candidate):
                return candidate
        return None

    def _extract_date(self, text: str) -> str | None:
        """Cerca la prima data in formato italiano o ISO nel testo."""
        match = _DATE_RE.search(text)
        return match.group(1) if match else None

    def _extract_total(self, text: str) -> str | None:
        """Cerca l'importo totale: prima una riga con etichetta nota (TOTALE/IMPORTO/
        DA PAGARE), altrimenti fallback sul valore in formato prezzo più alto trovato."""
        label_match = _TOTAL_LABEL_RE.search(text)
        if label_match:
            return label_match.group(2)

        amounts = _AMOUNT_ANY_RE.findall(text)
        if not amounts:
            return None
        return max(amounts, key=lambda a: float(a.replace(",", ".")))

    def _redact_pii(self, text: str) -> str:
        """
        Rete di sicurezza (difesa in profondità) sul nome esercizio estratto: scarta
        la riga se corrisponde a un'etichetta nota che precede un nome di terzi
        (cameriere, cassiere, cliente) e maschera sequenze numeriche lunghe.
        """
        if _PII_LABEL_RE.match(text):
            return "Esercizio non specificato"
        return _LONG_DIGIT_RE.sub("[NUMERO OMESSO]", text)

    def _log_field_missing(self, field: str, chat_id: str) -> None:
        """Log differenziato per campo mancante — un unico event name con
        meta.field per restare aggregabile da log analysis tooling (che
        raggruppa per domain/event), ma comunque distinguibile per causa."""
        logger.warning(
            "ocr_field_extraction_failed",
            extra={
                "domain": "usage",
                "event": "ocr_field_extraction_failed",
                "chat_id": chat_id,
                "meta": {"field": field},
            },
        )
