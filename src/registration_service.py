"""Domain service for capped, email-verified beta registration."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
import uuid

from sqlalchemy import func

from src.auth_tokens import (
    _consume_auth_token_in_session,
    _digest,
    _issue_auth_token_in_session,
)
from src.user_store import (
    AuditLog,
    AuthToken,
    PlanChange,
    ReferralReward,
    RegistrationCapacity,
    User,
    UserPlan,
    hash_password,
)


REGISTRATION_RESERVATION_TTL = timedelta(hours=24)
VERIFICATION_TOKEN_TTL = timedelta(hours=24)


class RegistrationCapacityReached(Exception):
    """Raised when all beta slots are occupied or reserved."""


class RegistrationEmailExists(Exception):
    """Raised when an email already belongs to a non-expired account."""


@dataclass(frozen=True)
class PendingRegistration:
    """Values needed to deliver and later consume a verification link."""

    user: User
    raw_token: str
    verification_token_digest: str


class RegistrationService:
    """Coordinate capacity, pending users and activation in database transactions."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalize an email consistently for uniqueness and lookup."""
        normalized = (email or "").strip().casefold()
        if not normalized or "@" not in normalized:
            raise ValueError("A valid email is required")
        return normalized

    @staticmethod
    def _validate_mandatory_consents(consents: dict) -> None:
        """Require the three blocking registration acknowledgements."""
        if not consents.get("privacy_policy_version"):
            raise ValueError("Privacy Policy acceptance is required")
        if not consents.get("tos_version"):
            raise ValueError("Terms acceptance is required")
        if consents.get("age_attestation") is not True:
            raise ValueError("Age attestation is required")

    def _capacity_row(self, session) -> RegistrationCapacity:
        """Lock or create the singleton capacity row."""
        capacity = (
            session.query(RegistrationCapacity)
            .filter(RegistrationCapacity.id == 1)
            .with_for_update()
            .first()
        )
        if capacity is None:
            capacity = RegistrationCapacity(id=1, max_accounts=50)
            session.add(capacity)
            session.flush()
        return capacity

    def _delete_expired_pending(self, session, now: datetime) -> None:
        """Release expired reservations and their outstanding verification tokens."""
        expired = session.query(User).filter(
            User.registration_status == "pending_verification",
            User.beta_slot_reserved_until <= now,
        ).all()
        for user in expired:
            session.query(AuthToken).filter(AuthToken.user_id == user.chat_id).delete(
                synchronize_session=False
            )
            session.delete(user)
        if expired:
            session.flush()

    def reserve(
        self,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        mandatory_consents: dict,
        referral_code: str | None = None,
    ) -> PendingRegistration:
        """Reserve one beta slot and create a pending user atomically."""
        normalized_email = self._normalize_email(email)
        self._validate_mandatory_consents(mandatory_consents)
        if not password:
            raise ValueError("Password is required")
        now = datetime.utcnow()
        with self.store.Session() as session:
            capacity = self._capacity_row(session)
            self._delete_expired_pending(session, now)
            existing = session.query(User).filter(
                func.lower(User.email) == normalized_email
            ).first()
            if existing is not None:
                raise RegistrationEmailExists("An account already exists for this email")

            active_count = session.query(User).filter(
                User.is_active.is_(True),
                User.registration_status == "active",
            ).count()
            pending_count = session.query(User).filter(
                User.registration_status == "pending_verification",
                User.beta_slot_reserved_until > now,
            ).count()
            if active_count + pending_count >= capacity.max_accounts:
                raise RegistrationCapacityReached("The beta is currently full")

            chat_id = f"web_{uuid.uuid4().hex}"
            user = User(
                chat_id=chat_id,
                email=normalized_email,
                password_hash=hash_password(password),
                first_name=(first_name or "").strip(),
                last_name=(last_name or "").strip(),
                registration_status="pending_verification",
                registration_source="web",
                storage_backend="postgres",
                beta_slot_reserved_until=now + REGISTRATION_RESERVATION_TTL,
                is_active=True,
                setup_status="COMPLETED",
                setup_completed_at=now,
                privacy_policy_version_accepted=mandatory_consents["privacy_policy_version"],
                privacy_accepted_at=now,
                tos_version_accepted=mandatory_consents["tos_version"],
                tos_accepted_at=now,
                age_attestation_at=now,
                referred_by_code=(referral_code or "").strip() or None,
            )
            session.add(user)
            session.flush()
            raw_token = _issue_auth_token_in_session(
                session, chat_id, "email_verification", VERIFICATION_TOKEN_TTL
            )
            session.commit()
            return PendingRegistration(
                user=user,
                raw_token=raw_token,
                verification_token_digest=_digest(raw_token),
            )

    def activate(self, raw_token: str) -> User | None:
        """Consume a verification token and activate the account with beta Pro."""
        now = datetime.utcnow()
        with self.store.Session() as session:
            user_id = _consume_auth_token_in_session(
                session, raw_token, "email_verification"
            )
            if user_id is None:
                return None
            user = session.query(User).filter(User.chat_id == user_id).first()
            if user is None or user.registration_status != "pending_verification":
                session.rollback()
                return None

            user.email_verified_at = now
            user.registration_status = "active"
            user.beta_slot_reserved_until = None
            user.referral_code = user.referral_code or secrets.token_urlsafe(6)
            self._create_direct_referral_rewards(session, user)
            session.add(
                UserPlan(
                    chat_id=user.chat_id,
                    plan_type="pro",
                    tokens_total=3_000_000,
                    tokens_reset_at=self.store._next_cycle_reset(now),
                    is_trial=False,
                )
            )
            session.add(
                PlanChange(
                    chat_id=user.chat_id,
                    from_plan="free",
                    to_plan="pro",
                    change_type="upgrade",
                    changed_at=now,
                    reason="beta_default",
                )
            )
            session.add(
                AuditLog(
                    user_id=user.chat_id,
                    actor="system",
                    action="registration_verified",
                    resource="web_registration",
                    metadata_json={"registration_source": "web"},
                )
            )
            session.commit()
            try:
                self.store.apply_pending_referral_rewards(user.email)
            except Exception:
                # Referral rewards are non-critical; activation remains successful.
                pass
            return user

    @staticmethod
    def _create_direct_referral_rewards(session, user: User) -> None:
        """Create pending rewards for a verified website referral."""
        if not user.referred_by_code or not user.email:
            return
        referrer = session.query(User).filter(
            User.referral_code == user.referred_by_code,
            User.chat_id != user.chat_id,
        ).first()
        if referrer is None or not referrer.email:
            return
        session.add(
            ReferralReward(
                beneficiary_email=user.email,
                beneficiary_chat_id=user.chat_id,
                role="referred",
                status="pending",
            )
        )
        referrer_rewards = session.query(ReferralReward).filter(
            ReferralReward.role == "referrer",
            ReferralReward.beneficiary_email == referrer.email,
        ).count()
        if referrer_rewards < 3:
            session.add(
                ReferralReward(
                    beneficiary_email=referrer.email,
                    beneficiary_chat_id=referrer.chat_id,
                    role="referrer",
                    status="pending",
                )
            )
