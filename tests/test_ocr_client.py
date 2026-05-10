import pytest
from unittest.mock import patch
from PIL import Image

from src.ocr_client import OcrClient, OCRError

pytestmark = pytest.mark.unit


def _make_real_image(width: int = 1200, height: int = 800) -> Image.Image:
    """Crea una piccola immagine PIL reale in RGB per i test.
    PIL.ImageEnhance.Contrast richiede pixel reali (non MagicMock).
    """
    return Image.new("RGB", (width, height), color=(200, 200, 200))


@patch("src.ocr_client.pytesseract.image_to_string", return_value="Totale: €12,50\nData: 01/04/2026")
@patch("src.ocr_client.Image.open")
def test_extract_text_success(mock_open, mock_tess):
    """Testo estratto correttamente da un'immagine leggibile."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    result = client.extract_text_from_image("/fake/receipt.jpg")

    assert "Totale" in result
    assert "12,50" in result
    mock_tess.assert_called_once()


@patch("src.ocr_client.pytesseract.image_to_string", return_value="   \n\n  ")
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_ocr_error_when_empty(mock_open, _mock_tess):
    """OCRError sollevata quando l'output è troppo corto (foto illeggibile)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRError):
        client.extract_text_from_image("/fake/dark_photo.jpg")


@patch("src.ocr_client.pytesseract.image_to_string", return_value="A")
@patch("src.ocr_client.Image.open")
def test_extract_text_raises_ocr_error_when_too_short(mock_open, _mock_tess):
    """OCRError sollevata quando il testo estratto è sotto soglia (< 10 char)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    with pytest.raises(OCRError):
        client.extract_text_from_image("/fake/blurry.jpg")


@patch("src.ocr_client.pytesseract.image_to_string", return_value="Esselunga 45,00 euro")
@patch("src.ocr_client.Image.open")
def test_preprocess_produces_grayscale(mock_open, mock_tess):
    """Verifica che il preprocessing produca un'immagine in scala di grigi (mode L)."""
    mock_open.return_value = _make_real_image()

    client = OcrClient()
    client.extract_text_from_image("/fake/receipt.jpg")

    # Il preprocessing converte in L; verifichiamo che pytesseract riceva un'immagine in L
    call_img = mock_tess.call_args[0][0]
    assert call_img.mode == "L"


@patch("src.ocr_client.pytesseract.image_to_string", return_value="Pane 2,00\nLatte 1,50")
@patch("src.ocr_client.Image.open")
def test_preprocess_upscales_small_images(mock_open, mock_tess):
    """Verifica che le immagini piccole vengano ingrandite prima dell'OCR."""
    mock_open.return_value = _make_real_image(width=400, height=600)

    client = OcrClient()
    client.extract_text_from_image("/fake/small.jpg")

    # Dopo il resize l'immagine passata a pytesseract deve avere larghezza >= 800
    call_img = mock_tess.call_args[0][0]
    assert call_img.width == 800
