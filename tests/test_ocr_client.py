import pytest
from unittest.mock import patch
from PIL import Image

from src.ocr_client import (
    OcrClient,
    OCRError,
    OCRMerchantNotFoundError,
    OCRDateNotFoundError,
    OCRTotalNotFoundError,
)

pytestmark = pytest.mark.unit


def _make_real_image(width: int = 1200, height: int = 800) -> Image.Image:
    """Crea una piccola immagine PIL reale in RGB per i test.
    PIL.ImageEnhance.Contrast richiede pixel reali (non MagicMock).
    """
    return Image.new("RGB", (width, height), color=(200, 200, 200))


_STANDARD_RECEIPT = (
    "ESSELUNGA\n"
    "Via Roma 1, Milano\n"
    "Tel: 02-12345678\n"
    "Pane integrale         1.29\n"
    "Latte fresco           1.45\n"
    "TOTALE EUR             2.74\n"
    "IVA 22% inclusa\n"
    "21/07/2026  14:32\n"
    "Scontrino n. 00247"
)

_PHARMACY_RECEIPT = (
    "FARMACIA CENTRALE\n"
    "Via Verdi 5, Roma\n"
    "Ibuprofene 400mg        4.90\n"
    "Collirio                8.50\n"
    "Cerotto medicato         5.20\n"
    "TOTALE EUR             18.60\n"
    "22/07/2026  09:10"
)


@patch("src.ocr_client.pytesseract.image_to_string", return_value=_STANDARD_RECEIPT)
@patch("src.ocr_client.Image.open")
def test_extract_text_success_returns_only_merchant_date_total(mock_open, mock_tess):
    """Estrae solo esercizio/data/totale, scartando indirizzo, telefono, articoli, IVA."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    result = client.extract_text_from_image("/fake/receipt.jpg", chat_id="123")

    assert "ESSELUNGA" in result
    assert "21/07/2026" in result
    assert "2.74" in result
    assert "Via Roma" not in result
    assert "02-12345678" not in result
    assert "Pane integrale" not in result
    assert "IVA" not in result
    mock_tess.assert_called_once()


@patch("src.ocr_client.pytesseract.image_to_string", return_value=_PHARMACY_RECEIPT)
@patch("src.ocr_client.Image.open")
def test_extract_text_never_leaks_drug_names(mock_open, _mock_tess):
    """Le righe articolo (nomi farmaco) non devono mai comparire nel risultato."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    result = client.extract_text_from_image("/fake/pharmacy.jpg", chat_id="123")

    assert "Ibuprofene" not in result
    assert "Collirio" not in result
    assert "FARMACIA CENTRALE" in result
    assert "18.60" in result


@patch("src.ocr_client.pytesseract.image_to_string", return_value="   \n\n  ")
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_ocr_error_when_empty(mock_open, _mock_tess):
    """OCRError sollevata quando l'output è troppo corto (foto illeggibile)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRError):
        client.extract_text_from_image("/fake/dark_photo.jpg", chat_id="123")


@patch("src.ocr_client.pytesseract.image_to_string", return_value="A")
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_ocr_error_when_too_short(mock_open, _mock_tess):
    """OCRError sollevata quando il testo estratto è sotto soglia (< 10 char)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRError):
        client.extract_text_from_image("/fake/blurry.jpg", chat_id="123")


@patch(
    "src.ocr_client.pytesseract.image_to_string",
    return_value="Esselunga\n21/07/2026\nGrazie mille",
)
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_total_not_found(mock_open, _mock_tess):
    """OCRTotalNotFoundError sollevata quando manca un importo in formato prezzo."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRTotalNotFoundError):
        client.extract_text_from_image("/fake/no_total.jpg", chat_id="123")


@patch(
    "src.ocr_client.pytesseract.image_to_string",
    return_value="Esselunga\nTOTALE EUR 12.50\nGrazie e arrivederci",
)
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_date_not_found(mock_open, _mock_tess):
    """OCRDateNotFoundError sollevata quando non c'è nessuna data riconoscibile."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRDateNotFoundError):
        client.extract_text_from_image("/fake/no_date.jpg", chat_id="123")


@patch(
    "src.ocr_client.pytesseract.image_to_string",
    return_value="999999\n888888\n777777\n21/07/2026\nTOTALE EUR 12.50",
)
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_merchant_not_found(mock_open, _mock_tess):
    """OCRMerchantNotFoundError sollevata quando nelle prime righe non c'è testo valido
    (solo cifre — l'euristica richiede almeno una lettera)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRMerchantNotFoundError):
        client.extract_text_from_image("/fake/no_merchant.jpg", chat_id="123")


@patch(
    "src.ocr_client.pytesseract.image_to_string",
    return_value="Ristorante Da Mario\nCameriere: Luca Rossi\nTOTALE EUR 25.00\n21/07/2026",
)
@patch("src.ocr_client.Image.open")
def test_extract_text_merchant_redaction_fallback(mock_open, _mock_tess):
    """Se l'euristica catturasse per errore una riga con etichetta di terzi, il
    denylist di difesa in profondità la sostituisce con un placeholder."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    result = client.extract_text_from_image("/fake/receipt.jpg", chat_id="123")

    assert "Luca Rossi" not in result
    assert "Ristorante Da Mario" in result


@patch("src.ocr_client.pytesseract.image_to_string", return_value=_STANDARD_RECEIPT)
@patch("src.ocr_client.Image.open")
def test_preprocess_produces_grayscale(mock_open, mock_tess):
    """Verifica che il preprocessing produca un'immagine in scala di grigi (mode L)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    client.extract_text_from_image("/fake/receipt.jpg", chat_id="123")

    # Il preprocessing converte in L; verifichiamo che pytesseract riceva un'immagine in L
    call_img = mock_tess.call_args[0][0]
    assert call_img.mode == "L"


@patch("src.ocr_client.pytesseract.image_to_string", return_value=_STANDARD_RECEIPT)
@patch("src.ocr_client.Image.open")
def test_preprocess_upscales_small_images(mock_open, mock_tess):
    """Verifica che le immagini piccole vengano ingrandite prima dell'OCR."""
    mock_open.return_value = _make_real_image(width=400, height=600)

    client = OcrClient()
    client.extract_text_from_image("/fake/small.jpg", chat_id="123")

    # Dopo il resize l'immagine passata a pytesseract deve avere larghezza >= 800
    call_img = mock_tess.call_args[0][0]
    assert call_img.width == 800
