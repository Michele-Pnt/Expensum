"""Repository per prenotazioni e consuntivi del consumo LLM."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.user_store import LlmTokenReservation, LlmUsageEvent


class LedgerRepository:
    """Operazioni coese sul ledger token, composte da ``UserStore``."""

    @staticmethod
    def _log(event: str, *, level: str, chat_id: str | None = None, error: Exception | None = None,
             meta: dict[str, object] | None = None) -> None:
        """Emette un evento strutturato usando il logger JSON Lines esistente."""
        # Import locale: evita il ciclo UserStore -> repository -> UserStore.
        from src.user_store import logger

        payload = dict(meta or {})
        if error is not None:
            payload["error_type"] = type(error).__name__
        extra: dict[str, object] = {"domain": "ledger", "event": event, "meta": payload}
        if chat_id is not None:
            extra["chat_id"] = str(chat_id)
        getattr(logger, level)(event, extra=extra, exc_info=error is not None)

    def reserve_llm_tokens(
        self,
        chat_id: str,
        request_key: str,
        operation: str,
        provider: str,
        model: str,
        reserved_tokens: int,
        ttl_minutes: int = 5,
    ) -> "LlmTokenReservation":
        """Prenota token LLM in modo idempotente prima della chiamata al provider."""
        from src.user_store import LlmTokenReservation, QuotaExceededError

        chat_id = str(chat_id)
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=ttl_minutes)
        plan_info = self.get_user_plan(chat_id)
        if plan_info["plan_type"] == "free" and plan_info["tokens_remaining"] < reserved_tokens:
            raise QuotaExceededError("Quota token insufficiente per la prenotazione.")
        if plan_info["plan_type"] == "pro" and plan_info["tokens_remaining"] < reserved_tokens:
            self._log(
                "pro_cap_hit",
                level="warning",
                chat_id=chat_id,
                meta={"tokens_remaining": plan_info["tokens_remaining"], "requested": reserved_tokens},
            )

        with self.Session() as session:
            existing = session.query(LlmTokenReservation).filter_by(request_key=request_key).first()
            if existing:
                self._log("llm_reservation_reused", level="debug", chat_id=chat_id)
                return existing
            reservation = LlmTokenReservation(
                chat_id=chat_id,
                request_key=request_key,
                created_at=now,
                expires_at=expires_at,
                operation=operation,
                provider=provider,
                model=model,
                reserved_tokens=reserved_tokens,
                status="pending",
            )
            session.add(reservation)
            session.commit()
            self._log("llm_reservation_created", level="debug", chat_id=chat_id)
            return reservation

    def finalize_llm_usage(
        self,
        chat_id: str,
        request_key: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str,
        model: str,
        operation: str,
        thinking_tokens: int | None = None,
        cached_tokens: int | None = None,
        input_method: str | None = None,
    ) -> "LlmUsageEvent":
        """Registra il consumo reale e chiude la relativa prenotazione, se presente."""
        from src.user_store import LlmPricing, LlmTokenReservation, LlmUsageEvent

        chat_id = str(chat_id)
        now = datetime.utcnow()
        with self.Session() as session:
            existing_event = session.query(LlmUsageEvent).filter_by(request_key=request_key).first()
            if existing_event:
                self._log("llm_usage_reused", level="debug", chat_id=chat_id)
                return existing_event
            pricing = session.query(LlmPricing).filter(
                LlmPricing.provider == provider,
                LlmPricing.model == model,
                LlmPricing.valid_to.is_(None),
            ).first()
            estimated_cost = None
            if pricing:
                input_cost = (Decimal(prompt_tokens) / 1000) * pricing.input_cost_per_1k
                output_cost = (Decimal(completion_tokens) / 1000) * pricing.output_cost_per_1k
                estimated_cost = (input_cost + output_cost).quantize(
                    Decimal("0.00000001"), rounding="ROUND_HALF_UP"
                )
            reservation = session.query(LlmTokenReservation).filter_by(request_key=request_key).first()
            reservation_id = None
            if reservation:
                reservation.status = "finalized"
                reservation_id = reservation.id
            event = LlmUsageEvent(
                chat_id=chat_id,
                occurred_at=now,
                provider=provider,
                model=model,
                operation=operation,
                input_method=input_method,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                thinking_tokens=thinking_tokens,
                cached_tokens=cached_tokens,
                estimated_cost_amount=estimated_cost,
                estimated_cost_currency=pricing.currency if pricing else "USD",
                request_key=request_key,
                reservation_id=reservation_id,
            )
            session.add(event)
            session.commit()
            self._log("llm_usage_finalized", level="debug", chat_id=chat_id)
            return event

    def release_llm_reservation(self, chat_id: str, request_key: str, reason: str = "") -> None:
        """Rilascia una prenotazione pending senza registrare il motivo libero nei log."""
        from src.user_store import LlmTokenReservation

        chat_id = str(chat_id)
        with self.Session() as session:
            reservation = session.query(LlmTokenReservation).filter_by(
                request_key=request_key, chat_id=chat_id
            ).first()
            if reservation and reservation.status == "pending":
                reservation.status = "released"
                reservation.release_reason = reason
                session.commit()
                self._log("llm_reservation_released", level="debug", chat_id=chat_id)

    def expire_stale_reservations(self) -> int:
        """Marca come scadute tutte le prenotazioni pending oltre il loro TTL."""
        from src.user_store import LlmTokenReservation

        with self.Session() as session:
            count = session.query(LlmTokenReservation).filter(
                LlmTokenReservation.status == "pending",
                LlmTokenReservation.expires_at < datetime.utcnow(),
            ).update({"status": "expired"})
            session.commit()
        if count:
            self._log("llm_reservations_expired", level="info", meta={"count": count})
        return count
