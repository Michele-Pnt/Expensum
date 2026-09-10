"""Repository per le operazioni di retention periodica."""

from datetime import datetime, timedelta


class RetentionRepository:
    """Elimina record scaduti senza accedere allo storage finanziario utente."""

    @staticmethod
    def _record_cleanup(event: str, count: int) -> None:
        """Invia il contatore aggregato al logger JSON Lines esistente."""
        from src.user_store import logger

        logger.info(event, extra={"domain": "retention", "event": event, "meta": {"count": count}})

    def cleanup_old_chat_messages(self, days: int = 90) -> int:
        """Elimina chat message oltre la finestra di retention configurata."""
        from src.user_store import ChatMessage

        with self.Session() as session:
            deleted = session.query(ChatMessage).filter(
                ChatMessage.created_at < datetime.utcnow() - timedelta(days=days)
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            self._record_cleanup("chat_messages_retained", deleted)
        return deleted

    def cleanup_old_notifications(self, days: int = 90) -> int:
        """Elimina notifiche in-app oltre la loro finestra di retention."""
        from src.storage.models import Notification

        with self.Session() as session:
            deleted = session.query(Notification).filter(
                Notification.created_at < datetime.utcnow() - timedelta(days=days)
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            self._record_cleanup("notifications_retained", deleted)
        return deleted

    def cleanup_stale_category_candidates(self, days: int = 90) -> int:
        """Elimina solo candidate categoria pending e non più utili."""
        from src.storage.models import CategoryCandidate

        with self.Session() as session:
            deleted = session.query(CategoryCandidate).filter(
                CategoryCandidate.status == "pending",
                CategoryCandidate.last_seen_at < datetime.utcnow() - timedelta(days=days),
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            self._record_cleanup("category_candidates_retained", deleted)
        return deleted

    def cleanup_stale_subscription_candidates(self, days: int = 120) -> int:
        """Elimina solo candidate abbonamento pending oltre la finestra più ampia."""
        from src.storage.models import SubscriptionCandidate

        with self.Session() as session:
            deleted = session.query(SubscriptionCandidate).filter(
                SubscriptionCandidate.status == "pending",
                SubscriptionCandidate.last_seen_at < datetime.utcnow() - timedelta(days=days),
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            self._record_cleanup("subscription_candidates_retained", deleted)
        return deleted

    def cleanup_old_job_runs(self, days: int = 90) -> int:
        """Elimina record di job scheduler oltre la retention operativa."""
        from src.user_store import JobRun

        with self.Session() as session:
            deleted = session.query(JobRun).filter(
                JobRun.finished_at < datetime.utcnow() - timedelta(days=days)
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            self._record_cleanup("job_runs_retained", deleted)
        return deleted
