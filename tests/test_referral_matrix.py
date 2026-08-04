"""
tests/test_referral_matrix.py — Matrice completa dei casi referral.

Copre ogni combinazione di (posizione nella catena di inviti) × (stato del piano di
chi riceve il reward) × (anti-abuso), perché il referral tocca il piano dell'utente
e un errore qui si traduce in giorni di Pro regalati o tolti per sbaglio.

Il flusso reale è: webhook Tally salva il lead -> `create_referral_rewards` scrive i
ReferralReward in stato 'pending' -> alla registrazione/login
`apply_pending_referral_rewards` li converte in giorni di Pro via `extend_trial_days`.
Nessun servizio esterno viene toccato.
"""

import pytest
from datetime import datetime, timedelta

from src.user_store import ReferralReward

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper che replicano il webhook /webhooks/tally (src/dashboard/app.py:398-412)
# ---------------------------------------------------------------------------

def _submit(store, submission_id, email, own_code=None, ref=None):
    """Un submit del form Tally."""
    return store.save_tally_lead(
        tally_submission_id=submission_id,
        email=email,
        raw_payload="{}",
        referral_code=own_code,
        referred_by_code=ref,
    )


def _webhook(store, submission_id, email, own_code, ref=None):
    """Il webhook completo, comprese le due guardie del chiamante reale.

    Le guardie sono `is_new` (retry del webhook) e `referrer_lead.id != lead.id`
    (auto-invito): stanno in app.py, non dentro create_referral_rewards.
    """
    lead, is_new = _submit(store, submission_id, email, own_code, ref)
    if not (is_new and ref):
        return lead, None
    referrer_lead = store.get_tally_lead_by_referral_code(ref)
    if not referrer_lead or referrer_lead.id == lead.id:
        return lead, None
    return lead, store.create_referral_rewards(lead, referrer_lead)


def _pending_days(store, email):
    """Giorni ancora in stato 'pending' per un'email."""
    with store.Session() as s:
        return sum(
            r.days_granted for r in s.query(ReferralReward).filter_by(
                beneficiary_email=email, status="pending",
            ).all()
        )


def _apply(store, email):
    """Applica i reward pendenti, ritorna i giorni concessi."""
    return sum(r.days_granted for r in store.apply_pending_referral_rewards(email))


REFERRER = "referrer@test.it"
CODE = "REF123"
DAYS = 14          # REFERRAL_REWARD_DAYS
MAX_REWARDED = 3   # REFERRER_MAX_REWARDED_REFERRALS


def _setup_referrer(store, with_account=True, chat_id="web_ref"):
    _submit(store, "s_ref", REFERRER, own_code=CODE)
    if with_account:
        store.add_user(chat_id=chat_id, email=REFERRER)
    return chat_id


# ---------------------------------------------------------------------------
# A — Chi prende cosa, in base alla posizione nella catena
# ---------------------------------------------------------------------------

class TestChainPosition:
    @pytest.fixture(autouse=True)
    def _store(self, mock_db_session):
        self.store = mock_db_session

    def test_A1_first_referral(self):
        _setup_referrer(self.store)
        _, result = _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)

        assert _pending_days(self.store, "a@test.it") == DAYS, "l'invitato prende 14gg"
        assert _pending_days(self.store, REFERRER) == DAYS, "il referrer prende 14gg"
        assert result["referrer_first_reward"] is True
        assert result["lifetime_founder_unlocked"] is False

    def test_A2_second_referral_accumulates_for_the_referrer(self):
        """Il bonus del referrer è per invito, non più unico."""
        _setup_referrer(self.store)
        _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)
        _, result = _webhook(self.store, "s2", "b@test.it", "codeB", ref=CODE)

        assert _pending_days(self.store, "b@test.it") == DAYS
        assert _pending_days(self.store, REFERRER) == 2 * DAYS, "14 + 14 = 28"
        assert result["referrer_first_reward"] is False, "non è più il primo"
        assert result["reward_cap_reached"] is False

    def test_A3_third_referral_unlocks_lifetime_founder(self):
        _setup_referrer(self.store)
        for i, email in enumerate(["a@test.it", "b@test.it", "c@test.it"], start=1):
            _, result = _webhook(self.store, f"s{i}", email, f"code{i}", ref=CODE)

        assert _pending_days(self.store, "c@test.it") == DAYS
        assert _pending_days(self.store, REFERRER) == 3 * DAYS, "42gg: il massimo per chi invita"
        assert result["lifetime_founder_unlocked"] is True
        assert self.store.get_tally_lead_by_referral_code(CODE).lifetime_founder_guaranteed

    def test_A4_link_never_expires_for_the_invited(self):
        """Il 4° invitato prende comunque i suoi giorni: il link non si esaurisce."""
        _setup_referrer(self.store)
        for i, email in enumerate(["a@test.it", "b@test.it", "c@test.it"], start=1):
            _webhook(self.store, f"s{i}", email, f"code{i}", ref=CODE)

        _, result = _webhook(self.store, "s4", "d@test.it", "codeD", ref=CODE)

        assert _pending_days(self.store, "d@test.it") == DAYS, "l'invitato è sempre premiato"
        assert result["reward_cap_reached"] is True, "ma il referrer ha finito i bonus"
        assert _pending_days(self.store, REFERRER) == 3 * DAYS, "resta a 42, non sale"

    def test_A4b_referrer_cap_holds_over_many_referrals(self):
        """Anche dopo dieci inviti il referrer resta a 42gg e gli invitati sono serviti."""
        _setup_referrer(self.store)
        for i in range(1, 11):
            _webhook(self.store, f"s{i}", f"u{i}@test.it", f"code{i}", ref=CODE)

        assert _pending_days(self.store, REFERRER) == MAX_REWARDED * DAYS
        for i in range(1, 11):
            assert _pending_days(self.store, f"u{i}@test.it") == DAYS

    def test_A5_lead_without_email_gets_nothing(self):
        _setup_referrer(self.store)
        _, result = _webhook(self.store, "s1", None, "codeA", ref=CODE)

        assert result == {
            "referrer_first_reward": False,
            "lifetime_founder_unlocked": False,
            "reward_cap_reached": False,
        }
        assert _pending_days(self.store, REFERRER) == 0

    def test_A6_unknown_referral_code_is_ignored(self):
        _setup_referrer(self.store)
        _, result = _webhook(self.store, "s1", "a@test.it", "codeA", ref="CODICE_INVENTATO")

        assert result is None
        assert _pending_days(self.store, "a@test.it") == 0


# ---------------------------------------------------------------------------
# B — Come reagisce il piano di chi riceve il reward
# ---------------------------------------------------------------------------

class TestPlanStates:
    @pytest.fixture(autouse=True)
    def _store(self, mock_db_session):
        self.store = mock_db_session
        _setup_referrer(self.store)
        _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)

    def test_B1_free_user_becomes_trial_pro(self):
        assert _apply(self.store, REFERRER) == DAYS

        plan = self.store.get_user_plan("web_ref")
        assert plan["plan_type"] == "pro"
        assert plan["is_trial"] is True
        assert DAYS - 1 <= (plan["trial_ends_at"] - datetime.utcnow()).days <= DAYS

    def test_B2_active_trial_is_extended_additively(self):
        self.store.start_trial("web_ref", days=10)
        before = self.store.get_user_plan("web_ref")["trial_ends_at"]

        _apply(self.store, REFERRER)

        after = self.store.get_user_plan("web_ref")["trial_ends_at"]
        assert (after - before).days == DAYS, "si somma alla scadenza, non la sovrascrive"

    def test_B3_expired_trial_restarts_from_today(self):
        """Un trial scaduto non deve regalare giorni retroattivi."""
        from src.user_store import UserPlan

        self.store.start_trial("web_ref", days=10)
        with self.store.Session() as s:
            plan = s.query(UserPlan).filter_by(chat_id="web_ref").first()
            plan.trial_ends_at = datetime.utcnow() - timedelta(days=5)
            s.commit()

        _apply(self.store, REFERRER)

        ends = self.store.get_user_plan("web_ref")["trial_ends_at"]
        assert DAYS - 1 <= (ends - datetime.utcnow()).days <= DAYS

    def test_B4_permanent_pro_is_not_downgraded(self):
        """La regressione principale: il Pro illimitato non diventa un trial."""
        self.store.set_user_plan("web_ref", "pro", payment_reference="beta_default")

        _apply(self.store, REFERRER)

        plan = self.store.get_user_plan("web_ref")
        assert plan["is_trial"] is False
        assert plan["trial_ends_at"] is None
        assert self.store.get_pending_pro_days("web_ref") == DAYS, "in credito, non persi"

    def test_B5_credit_is_redeemed_when_pro_ends(self):
        self.store.set_user_plan("web_ref", "pro", payment_reference="beta_default")
        _apply(self.store, REFERRER)

        self.store.set_user_plan("web_ref", "free", payment_reference="trial_expired")

        plan = self.store.get_user_plan("web_ref")
        assert plan["plan_type"] == "pro", "il credito lo riporta Pro"
        assert plan["is_trial"] is True
        assert self.store.get_pending_pro_days("web_ref") == 0


# ---------------------------------------------------------------------------
# C — Momento dell'applicazione
# ---------------------------------------------------------------------------

class TestApplication:
    @pytest.fixture(autouse=True)
    def _store(self, mock_db_session):
        self.store = mock_db_session

    def test_C1_reward_waits_for_the_account(self):
        _setup_referrer(self.store, with_account=False)
        _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)

        assert _apply(self.store, "a@test.it") == 0, "nessun account: nulla da applicare"
        assert _pending_days(self.store, "a@test.it") == DAYS, "ma il reward non è perso"

        self.store.add_user(chat_id="web_a", email="a@test.it")
        assert _apply(self.store, "a@test.it") == DAYS

    def test_C2_double_application_is_idempotent(self):
        _setup_referrer(self.store)
        _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)

        _apply(self.store, REFERRER)
        first_end = self.store.get_user_plan("web_ref")["trial_ends_at"]

        assert _apply(self.store, REFERRER) == 0
        assert self.store.get_user_plan("web_ref")["trial_ends_at"] == first_end

    def test_C3_being_both_referrer_and_invited_sums_the_rewards(self):
        """Chi è stato invitato e poi invita a sua volta cumula i due reward."""
        # Alice invita Bob.
        _submit(self.store, "s_alice", "alice@test.it", own_code="ALICE")
        _webhook(self.store, "s_bob", "bob@test.it", "BOB", ref="ALICE")
        # Bob a sua volta invita Carol.
        _webhook(self.store, "s_carol", "carol@test.it", "CAROL", ref="BOB")

        self.store.add_user(chat_id="web_bob", email="bob@test.it")
        assert _apply(self.store, "bob@test.it") == 2 * DAYS, "14 da invitato + 14 da referrer"

        plan = self.store.get_user_plan("web_bob")
        assert 2 * DAYS - 1 <= (plan["trial_ends_at"] - datetime.utcnow()).days <= 2 * DAYS


# ---------------------------------------------------------------------------
# D — Anti-abuso
# ---------------------------------------------------------------------------

class TestAbuse:
    @pytest.fixture(autouse=True)
    def _store(self, mock_db_session):
        self.store = mock_db_session

    def test_D1_webhook_retry_creates_nothing(self):
        """Tally può ripetere lo stesso submissionId: `is_new` lo blocca."""
        _setup_referrer(self.store)
        _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)
        _, result = _webhook(self.store, "s1", "a@test.it", "codeA", ref=CODE)

        assert result is None, "il retry non passa la guardia is_new"
        assert _pending_days(self.store, "a@test.it") == DAYS, "non raddoppia"

    def test_D2_self_referral_same_submission_is_blocked(self):
        _submit(self.store, "s1", "solo@test.it", own_code=CODE)
        _, result = _webhook(self.store, "s1", "solo@test.it", CODE, ref=CODE)

        assert result is None
        assert _pending_days(self.store, "solo@test.it") == 0

    def test_D3_self_referral_with_a_second_submission_is_blocked(self):
        """Stessa email, secondo submit col proprio codice: nessun reward.

        Regressione del buco chiuso: l'idempotenza di `save_tally_lead` è su
        `tally_submission_id`, quindi due submit della stessa persona producono lead
        con id diversi. Una guardia basata sugli id non li riconosceva come la stessa
        identità e regalava il doppio bonus. Ora il confronto è sulle email.
        """
        _submit(self.store, "s1", "solo@test.it", own_code=CODE)
        _, result = _webhook(self.store, "s2", "solo@test.it", "codeB", ref=CODE)

        self.store.add_user(chat_id="web_solo", email="solo@test.it")

        assert _apply(self.store, "solo@test.it") == 0, "nessun giorno all'auto-invitante"
        assert result == {
            "referrer_first_reward": False,
            "lifetime_founder_unlocked": False,
            "reward_cap_reached": False,
        }

    def test_D4_self_referral_is_case_and_space_insensitive(self):
        """Maiuscole e spazi non devono aggirare la guardia."""
        _submit(self.store, "s1", "solo@test.it", own_code=CODE)
        _, result = _webhook(self.store, "s2", "  SOLO@Test.IT  ", "codeB", ref=CODE)

        self.store.add_user(chat_id="web_solo", email="solo@test.it")
        assert _apply(self.store, "solo@test.it") == 0

    def test_D5_the_store_blocks_self_referral_even_without_the_webhook_guard(self):
        """Difesa in profondità: la guardia vive anche dentro create_referral_rewards."""
        lead_a, _ = _submit(self.store, "s1", "solo@test.it", own_code=CODE)
        lead_b, _ = _submit(self.store, "s2", "solo@test.it", own_code="codeB", ref=CODE)

        # Chiamata diretta, saltando le guardie del webhook.
        result = self.store.create_referral_rewards(lead_b, lead_a)

        assert result["referrer_first_reward"] is False
        assert _pending_days(self.store, "solo@test.it") == 0
