"""src/notification_service.py — Centro notifiche in-app.

Copre eventi asincroni che possono verificarsi indipendentemente dal fatto che
l'utente stia usando la webapp in quel momento (report periodici, addebiti
ricorrenti, inattività, anomalie di sicurezza, messaggi admin). Fa eccezione,
per scelta esplicita del prodotto, la soglia di budget raggiunta/superata: pur
scattando in risposta sincrona all'inserimento di una spesa (che resta comunque
mostrato come feedback UI immediato nello stesso messaggio), genera anche una
riga persistente qui, perché è uno stato del mese («hai sforato») utile a
ritrovare anche dopo, non solo nell'istante in cui si verifica.

Layer sottile e backend-agnostico rispetto allo storage finanziario: `Notification`
non è un dato finanziario dell'utente, quindi non serve l'astrazione Notion/Postgres
defined by the storage architecture — usa direttamente una `Session` SQLAlchemy, stesso pattern
di `src/subscription_detector.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.storage.models import Notification

logger = logging.getLogger("financial_agent.notification_service")

# Tipi riconosciuti — vedi il docstring di modulo per il criterio di ammissione.
NOTIFICATION_TYPES = frozenset({
    "weekly_report",
    "monthly_report",
    "budget_reached",
    "budget_exceeded",
    "recurring_charge",
    "inactivity",
    "security_anomaly",
    "admin_message",
})

PRIORITIES = frozenset({"info", "warning", "critical"})


def create_notification(
    session: Session,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    payload: Optional[dict] = None,
    priority: str = "info",
) -> Notification:
    """Crea e committa una notifica per l'utente.

    Non solleva su `notification_type`/`priority` ignoti: logga solo un warning
    e prosegue comunque (`priority` ricade su "info") — un tipo nuovo non ancora
    aggiunto a `NOTIFICATION_TYPES` non deve mai bloccare l'evento che lo genera.
    """
    if notification_type not in NOTIFICATION_TYPES:
        logger.warning(
            "Tipo notifica non riconosciuto: %s", notification_type,
            extra={"domain": "app", "event": "unknown_notification_type", "meta": {}},
        )
    notification = Notification(
        user_id=str(user_id),
        type=notification_type,
        title=title,
        body=body,
        payload=payload,
        priority=priority if priority in PRIORITIES else "info",
    )
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification


def list_notifications(
    session: Session,
    user_id: str,
    unread_only: bool = False,
    limit: int = 20,
    before_id: Optional[int] = None,
) -> list[Notification]:
    """Lista paginata, più recenti prima. `before_id` pagina all'indietro (cursor)."""
    query = session.query(Notification).filter(Notification.user_id == str(user_id))
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    if before_id is not None:
        query = query.filter(Notification.id < before_id)
    return query.order_by(Notification.id.desc()).limit(limit).all()


def count_unread(session: Session, user_id: str) -> int:
    """Conta le notifiche non lette dell'utente, per il badge della campanella."""
    return (
        session.query(Notification)
        .filter(Notification.user_id == str(user_id), Notification.read_at.is_(None))
        .count()
    )


def mark_read(session: Session, user_id: str, notification_id: int) -> bool:
    """Segna come letta una notifica dell'utente. Ritorna False se non esiste/non è sua."""
    notification = (
        session.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == str(user_id))
        .first()
    )
    if not notification:
        return False
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        session.commit()
    return True


def mark_all_read(session: Session, user_id: str) -> int:
    """Segna come lette tutte le notifiche non lette dell'utente. Ritorna il conteggio."""
    updated = (
        session.query(Notification)
        .filter(Notification.user_id == str(user_id), Notification.read_at.is_(None))
        .update({"read_at": datetime.utcnow()}, synchronize_session=False)
    )
    session.commit()
    return updated
