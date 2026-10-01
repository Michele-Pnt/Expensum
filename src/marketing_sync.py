"""Retryable synchronization of marketing consent with Brevo."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from config import Config
from src import brevo_client
from src.consent_service import ConsentService
from src.user_store import MarketingSyncTask, User


@dataclass(frozen=True)
class SyncSummary:
    """Counts for one outbox processing pass."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0


def process_marketing_sync_tasks(
    store, now: datetime | None = None, limit: int = 100
) -> SyncSummary:
    """Dispatch due desired states while respecting later withdrawals."""
    now = now or datetime.utcnow()
    with store.Session() as session:
        tasks = session.query(MarketingSyncTask).filter(
            MarketingSyncTask.status == "pending",
            MarketingSyncTask.next_retry_at <= now,
        ).order_by(MarketingSyncTask.id).limit(limit).all()

    processed = succeeded = failed = 0
    for task in tasks:
        processed += 1
        with store.Session() as session:
            current = session.query(MarketingSyncTask).filter_by(id=task.id).first()
            user = session.query(User).filter_by(chat_id=task.user_id).first()
            if current is None or current.status != "pending" or user is None:
                continue
            latest_task_id = session.query(MarketingSyncTask.id).filter(
                MarketingSyncTask.user_id == task.user_id,
                MarketingSyncTask.status == "pending",
            ).order_by(MarketingSyncTask.id.desc()).first()
            latest_task_id = latest_task_id[0] if latest_task_id else None
            if latest_task_id != current.id:
                current.status = "superseded"
                session.commit()
                continue
            latest = ConsentService(store).current(task.user_id)["marketing_email"]
            desired = "granted" if latest else "withdrawn"
            if desired != current.desired_state:
                current.desired_state = desired
                current.consent_event_id = _latest_marketing_event_id(session, task.user_id)
            email = user.email
            session.commit()
        try:
            if desired == "granted":
                brevo_client.upsert_contact(
                    email, list_ids=[Config.BREVO_MARKETING_LIST_ID]
                )
            else:
                brevo_client.remove_contact_from_list(
                    email, Config.BREVO_MARKETING_LIST_ID
                )
        except Exception as exc:
            with store.Session() as session:
                current = session.query(MarketingSyncTask).filter_by(id=task.id).first()
                if current:
                    current.attempt_count += 1
                    current.last_error_code = type(exc).__name__[:64]
                    current.next_retry_at = now + timedelta(
                        minutes=min(2 ** current.attempt_count, 240)
                    )
                    session.commit()
            failed += 1
            continue
        with store.Session() as session:
            current = session.query(MarketingSyncTask).filter_by(id=task.id).first()
            if current:
                current.status = "completed"
                current.last_error_code = None
                session.commit()
        succeeded += 1
    return SyncSummary(processed=processed, succeeded=succeeded, failed=failed)


def _latest_marketing_event_id(session, user_id: str) -> int:
    """Return the latest event id for the marketing purpose."""
    from src.user_store import ConsentEvent

    event = session.query(ConsentEvent).filter(
        ConsentEvent.user_id == user_id,
        ConsentEvent.consent_type == "marketing_email",
    ).order_by(ConsentEvent.created_at.desc(), ConsentEvent.id.desc()).first()
    return event.id
