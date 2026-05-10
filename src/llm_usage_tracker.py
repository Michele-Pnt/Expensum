"""Utilities per request key, reservation e usage metadata LLM."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


_RESERVATION_MAP = {
    "expense_parse": 800,
    "voice_transcribe": 1500,
    "photo_ocr": 2000,
    "weekly_report": 5000,
    "monthly_report": 5000,
    "weekly_plan": 3000,
    "monthly_plan": 3000,
}


def build_request_key(*parts: Any) -> str:
    """Crea una request key stabile a partire da più componenti."""
    payload = "|".join(_serialize_part(part) for part in parts)
    return sha256(payload.encode("utf-8")).hexdigest()


def estimate_reserved_tokens(operation: str) -> int:
    """Restituisce una stima conservativa dei token da riservare."""
    return _RESERVATION_MAP.get(operation, 2000)


def normalize_usage_metadata(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Riempie i campi mancanti delle usage metadata e garantisce total_tokens."""
    normalized = dict(usage or {})
    prompt_tokens = int(normalized.get("prompt_tokens", 0) or 0)
    completion_tokens = int(normalized.get("completion_tokens", 0) or 0)
    total_tokens = int(normalized.get("total_tokens", 0) or 0)
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    normalized["prompt_tokens"] = prompt_tokens
    normalized["completion_tokens"] = completion_tokens
    normalized["total_tokens"] = total_tokens
    return normalized


def _serialize_part(part: Any) -> str:
    if isinstance(part, (dict, list, tuple)):
        return json.dumps(part, sort_keys=True, ensure_ascii=True, default=str)
    return str(part)