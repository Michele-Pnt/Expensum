"""
src/input_sanitizer.py — Sanitizzazione input multimodale contro prompt injection.

Protezioni implementate (OWASP LLM01:2025):
- Pattern matching su frasi di injection note (IT + EN)
- Rimozione caratteri Unicode pericolosi (zero-width, RTL override, BOM)
- Normalizzazione Unicode per neutralizzare omoglifi/obfuscation
- Cap sulla lunghezza per prevenire token flooding
"""

import logging
import re
import unicodedata

logger = logging.getLogger("financial_agent.input_sanitizer")

# Lunghezze massime per testo proveniente da sorgenti non testuali
_MAX_OCR_LEN = 3000   # testo estratto da foto scontrino
_MAX_AUDIO_LEN = 1500  # testo trascritto da audio
_MAX_CATEGORY_NAME_LEN = 80
_MAX_CATEGORY_DESCRIPTION_LEN = 500

# Caratteri Unicode usati per obfuscare iniezioni
_DANGEROUS_CHARS = {
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u202a",  # left-to-right embedding
    "\u202b",  # right-to-left embedding
    "\u202c",  # pop directional formatting
    "\u202d",  # left-to-right override
    "\u202e",  # right-to-left override (usato per invertire testo malevolo)
    "\u2060",  # word joiner
    "\u2061",  # function application
    "\u2062",  # invisible times
    "\u2063",  # invisible separator
    "\u2064",  # invisible plus
    "\ufeff",  # byte order mark / zero-width no-break space
    "\u00ad",  # soft hyphen (usato per spezzare parole chiave)
    "\u034f",  # combining grapheme joiner
}

# Pattern di prompt injection — IT e EN, con e senza spazi intenzionali
# Ordinati per specificità crescente (più generici ultimi)
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Override diretto delle istruzioni di sistema
    (r"\bistruzioni\s+precedenti\b", "override_system_it"),
    (r"\bprevious\s+instructions?\b", "override_system_en"),
    (r"\bsystem\s*[_\-]?\s*prompt\b", "system_prompt_ref"),
    (r"\bignora\s+(?:le\s+)?(?:tue\s+)?(?:istruzioni|regole|vincoli|limiti)\b", "ignore_rules_it"),
    (r"\bignore\s+(?:your\s+)?(?:instructions?|rules?|constraints?|guidelines?)\b", "ignore_rules_en"),
    (r"\bdimentica\s+(?:tutto|le\s+istruzioni|le\s+regole|chi\s+sei)\b", "forget_it"),
    (r"\bforget\s+(?:everything|your\s+instructions?|who\s+you\s+are)\b", "forget_en"),
    # Cambio identità / jailbreak
    (r"\b(?:sei\s+ora|ora\s+sei)\s+(?:un|una|il|la)\b", "role_change_it"),
    (r"\byou\s+are\s+now\s+(?:a|an|the)\b", "role_change_en"),
    (r"\bact\s+as\s+(?:a|an|if)\b", "act_as_en"),
    (r"\bagisci\s+come\s+(?:se\s+)?(?:un|una|fossi)\b", "act_as_it"),
    (r"\bfingi\s+di\s+essere\b", "pretend_it"),
    (r"\bpretend\s+(?:to\s+be|you\s+are)\b", "pretend_en"),
    (r"\bjailbreak\b", "jailbreak"),
    (r"\b(?:DAN|do\s+anything\s+now)\b", "dan_mode"),
    (r"\bmodalità?\s*(?:dio|god|admin|developer|sviluppatore|debug|senza\s+restrizioni)\b", "god_mode_it"),
    (r"\b(?:god|admin|developer|debug|unrestricted)\s*mode\b", "god_mode_en"),
    # Estrazione dati / file system
    (r"\b(?:mostra|stampa|print|dump|esporta|export|reveal|show)\b.{0,30}\b(?:token|chiav\w+|key|secret|password|config|env|credential)\b", "data_exfil"),
    (r"\b(?:leggi|read|accedi|access|apri|open)\b.{0,30}\b(?:file|\.env|database|db|sistema|system|disco|disk)\b", "file_access"),
    # Delimitatori di prompt tipici dei modelli
    (r"<\|?\s*(?:system|user|assistant|im_start|im_end|endoftext)\s*\|?>", "prompt_delimiters"),
    (r"\[(?:SISTEMA|SYSTEM|ADMIN|INST|\/INST)\]", "prompt_brackets"),
    (r"###\s*(?:System|Instruction|Override)", "markdown_injection"),
    # Codifiche e bypass
    (r"\bbase64\b", "encoding_bypass"),
    (r"\bbypass\b.{0,20}\b(?:filter|filtro|protezione|protection|sicurezza|security)\b", "filter_bypass"),
]

_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE | re.UNICODE), label)
    for pattern, label in _INJECTION_PATTERNS
]


class InjectionDetectedError(ValueError):
    """Sollevata quando viene rilevato un tentativo di prompt injection."""

    def __init__(self, source: str, matched_label: str):
        self.source = source
        self.matched_label = matched_label
        super().__init__(f"Injection detected in {source}: {matched_label}")


def sanitize_ocr_text(text: str, chat_id: str) -> str:
    """
    Sanitizza testo estratto da OCR foto scontrino.

    Raises:
        InjectionDetectedError: Se vengono rilevati pattern di injection.
    """
    return _sanitize(text, source="ocr", max_len=_MAX_OCR_LEN, chat_id=chat_id)


def sanitize_audio_transcription(text: str, chat_id: str) -> str:
    """
    Sanitizza testo trascritto da audio vocale.

    Raises:
        InjectionDetectedError: Se vengono rilevati pattern di injection.
    """
    return _sanitize(text, source="audio", max_len=_MAX_AUDIO_LEN, chat_id=chat_id)


def sanitize_category_metadata(
    text: str, chat_id: str, *, field: str,
) -> str:
    """Validate category metadata before persistence or use in an LLM prompt.

    Category names and descriptions are user-controlled text.  They use the same
    Unicode normalization and injection detection as OCR/audio, with stricter
    field-specific limits.
    """
    max_len = _MAX_CATEGORY_NAME_LEN if field == "name" else _MAX_CATEGORY_DESCRIPTION_LEN
    return _sanitize(text, source=f"category_{field}", max_len=max_len, chat_id=chat_id)


def _sanitize(text: str, source: str, max_len: int, chat_id: str) -> str:
    """Pipeline di sanitizzazione: Unicode → lunghezza → pattern injection."""
    # 1. Normalizzazione Unicode NFC — riduce omoglifi e sequenze composte
    text = unicodedata.normalize("NFC", text)

    # 2. Rimozione caratteri pericolosi usati per obfuscare iniezioni
    cleaned = "".join(ch for ch in text if ch not in _DANGEROUS_CHARS)
    if len(cleaned) < len(text):
        removed = len(text) - len(cleaned)
        logger.warning(
            "suspicious_unicode_removed",
            extra={"domain": "security", "event": "suspicious_unicode_removed",
                   "chat_id": chat_id, "meta": {"source": source, "removed_chars": removed}},
        )
    text = cleaned

    # 3. Cap sulla lunghezza — previene token flooding
    if len(text) > max_len:
        logger.warning(
            "input_truncated",
            extra={"domain": "security", "event": "input_truncated",
                   "chat_id": chat_id, "meta": {"source": source, "original_len": len(text), "max_len": max_len}},
        )
        text = text[:max_len]

    # 4. Rilevamento pattern injection
    _detect_injection(text, source=source, chat_id=chat_id)

    return text


def _detect_injection(text: str, source: str, chat_id: str) -> None:
    """
    Scansiona il testo alla ricerca di pattern di prompt injection.

    Raises:
        InjectionDetectedError: Se viene trovato un pattern sospetto.
    """
    for pattern, label in _COMPILED:
        if pattern.search(text):
            logger.warning(
                "injection_detected",
                extra={
                    "domain": "security",
                    "event": "injection_detected",
                    "chat_id": chat_id,
                    "meta": {"source": source, "pattern": label},
                },
            )
            raise InjectionDetectedError(source=source, matched_label=label)
