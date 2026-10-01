"""Append-only optional consent management and marketing outbox creation."""

from datetime import datetime

from src.user_store import ConsentEvent, MarketingSyncTask


class InvalidConsentCombination(ValueError):
    """Raised when a source-specific consent lacks its parent purpose."""


class ConsentService:
    """Record and derive versioned consent choices for one user store."""

    OPTIONAL_CONSENTS = (
        "product_analytics",
        "marketing_email",
        "algorithm_improvement",
        "structured_text_usage",
        "structured_voice_usage",
        "ocr_text_usage",
    )
    SOURCE_CONSENTS = frozenset(
        {"structured_text_usage", "structured_voice_usage", "ocr_text_usage"}
    )

    def __init__(self, store) -> None:
        """Initialize the service with the repository owning the transaction."""
        self.store = store

    def record(
        self,
        user_id: str,
        consent_type: str,
        granted: bool,
        version: str,
        source: str,
    ) -> ConsentEvent:
        """Append one changed consent event and queue marketing synchronization."""
        if consent_type not in self.OPTIONAL_CONSENTS:
            raise ValueError(f"Unknown optional consent: {consent_type}")
        with self.store.Session() as session:
            current = self._current_in_session(session, user_id)
            self._validate_combination(consent_type, granted, current)
            event = ConsentEvent(
                user_id=str(user_id),
                consent_type=consent_type,
                granted=bool(granted),
                version=version,
                source=source,
                created_at=datetime.utcnow(),
            )
            session.add(event)
            session.flush()
            if consent_type == "marketing_email":
                session.add(
                    MarketingSyncTask(
                        user_id=str(user_id),
                        consent_event_id=event.id,
                        desired_state="granted" if granted else "withdrawn",
                    )
                )
            session.commit()
            if not granted and consent_type in {
                "algorithm_improvement", *self.SOURCE_CONSENTS
            }:
                from src.ai_improvement import delete_user_quality_samples

                delete_user_quality_samples(self.store, user_id)
            return event

    def record_batch(
        self,
        user_id: str,
        choices: dict[str, bool],
        source: str,
        version: str = "2026-10-01",
    ) -> list[ConsentEvent]:
        """Expand bulk choices and append a validated batch of consent events."""
        expanded = self._expand_choices(choices)
        current = self.current(user_id)
        prospective = {**current, **expanded}
        if not prospective.get("algorithm_improvement", False) and any(
            prospective.get(name, False) for name in self.SOURCE_CONSENTS
        ):
            raise InvalidConsentCombination(
                "Source-specific AI consent requires algorithm_improvement"
            )
        return [
            self.record(user_id, consent_type, granted, version, source)
            for consent_type, granted in expanded.items()
            if current.get(consent_type) != granted
        ]

    def current(self, user_id: str) -> dict[str, bool]:
        """Return the latest known value for every optional consent purpose."""
        with self.store.Session() as session:
            return self._current_in_session(session, user_id)

    def history(self, user_id: str, consent_type: str | None = None) -> list[ConsentEvent]:
        """Return append-only consent history ordered oldest to newest."""
        with self.store.Session() as session:
            query = session.query(ConsentEvent).filter(ConsentEvent.user_id == str(user_id))
            if consent_type:
                query = query.filter(ConsentEvent.consent_type == consent_type)
            return query.order_by(ConsentEvent.created_at, ConsentEvent.id).all()

    def _expand_choices(self, choices: dict[str, bool]) -> dict[str, bool]:
        """Expand accept/reject-all commands against the server allowlist."""
        if choices.get("accept_all") is True:
            return {name: True for name in self.OPTIONAL_CONSENTS}
        if choices.get("reject_all") is True:
            return {name: False for name in self.OPTIONAL_CONSENTS}
        unknown = set(choices) - set(self.OPTIONAL_CONSENTS)
        if unknown:
            raise ValueError("Unknown optional consent")
        return {name: bool(value) for name, value in choices.items()}

    @classmethod
    def _current_in_session(cls, session, user_id: str) -> dict[str, bool]:
        """Derive current state without mutating the append-only event log."""
        values = {name: False for name in cls.OPTIONAL_CONSENTS}
        events = session.query(ConsentEvent).filter(
            ConsentEvent.user_id == str(user_id)
        ).order_by(ConsentEvent.created_at, ConsentEvent.id)
        for event in events:
            if event.consent_type in values:
                values[event.consent_type] = bool(event.granted)
        return values

    @classmethod
    def _validate_combination(
        cls, consent_type: str, granted: bool, current: dict[str, bool]
    ) -> None:
        """Validate the parent/source dependency before writing an event."""
        if consent_type in cls.SOURCE_CONSENTS and granted and not current.get(
            "algorithm_improvement", False
        ):
            raise InvalidConsentCombination(
                "Source-specific AI consent requires algorithm_improvement"
            )
