"""
src/ocr_client.py — Tesseract OCR wrapper per estrazione testo da foto scontrini.

Pipeline: immagine → preprocessing PIL → pytesseract (ita) → testo pulito.
Tutto gira in locale sulla VPS: zero trasferimento dati, GDPR compliant.
"""

import logging
import re

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger("financial_agent.ocr")

# Soglia minima di caratteri per considerare l'OCR riuscito
_MIN_TEXT_LENGTH = 10


class OCRError(Exception):
    """Sollevata quando Tesseract non riesce a estrarre testo leggibile."""


class OcrClient:
    """Wrapper Tesseract OCR con preprocessing immagine per scontrini."""

    def extract_text_from_image(self, image_path: str) -> str:
        """
        Estrae testo da un'immagine usando Tesseract OCR con lingua italiana.

        Args:
            image_path: Percorso assoluto all'immagine (JPEG, PNG, ecc.)

        Returns:
            Testo estratto, pulito da righe vuote eccessive.

        Raises:
            OCRError: Se il testo estratto è inferiore a 10 caratteri (foto illeggibile).
        """
        logger.info(f"OCR su immagine: {image_path}")

        img = Image.open(image_path)
        img = self._preprocess(img)

        raw_text = pytesseract.image_to_string(img, lang="ita")
        cleaned = self._clean(raw_text)

        if len(cleaned) < _MIN_TEXT_LENGTH:
            logger.warning(f"OCR: testo troppo corto ({len(cleaned)} char) — foto probabilmente illeggibile")
            raise OCRError("testo non leggibile")

        logger.info(f"OCR completato: {len(cleaned)} caratteri estratti")
        return cleaned

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
