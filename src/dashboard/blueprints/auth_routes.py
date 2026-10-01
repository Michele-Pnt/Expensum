"""Autenticazione: ingresso web app, login/logout/registrazione, login admin,
OAuth Notion, registrazione Postgres, login Telegram Mini App, stato sessione.

Blueprint leaf: legge lo store condiviso via `current_app.config["STORE"]`, mai
import diretto di `app.py`/`factory.py` (nessun ciclo). Attenzione:
`enforce_csrf_on_forms` (in factory.py) esenta `/auth/telegram-login` per
**path**, non per endpoint — spostare questa route in un blueprint non cambia
l'esenzione CSRF, che va comunque preservata.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta

import requests
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from markupsafe import escape

from config import Config
from src import analytics
from src import brevo_client
from src.category_sync import refresh_category_averages
from src.dashboard.auth import (
    _get_session_chat_id,
    _get_user_by_chat_id,
    _resolve_request_chat_id,
    _user_has_web_access,
)
from src.dashboard.extensions import limiter
from src.dashboard.referrals import _send_referral_reward_emails
from src.notification_service import create_notification
from src.auth_tokens import issue_auth_token
from src.registration_service import (
    RegistrationCapacityReached,
    RegistrationEmailExists,
    RegistrationService,
)
from src.notion_client import NotionFinanceClient
from src.storage.models import Notification
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.workspace_bootstrapper import bootstrap_workspace

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Timeout condiviso per le chiamate verso Telegram/Notion: con solo 2 worker
# gunicorn, una richiesta senza timeout che si blocca satura il servizio per
# tutti gli utenti (vedi bandit B113).
TELEGRAM_REQUEST_TIMEOUT = 10

# Account lockout su /login: oltre questa soglia di fallimenti nella finestra,
# l'account (per email) resta bloccato indipendentemente dall'IP di provenienza
# — il rate limit di flask_limiter qui sotto è per-IP e da solo è bypassabile
# semplicemente cambiando IP.
ACCOUNT_LOCKOUT_THRESHOLD = 5
ACCOUNT_LOCKOUT_WINDOW_SECONDS = 900

ADMIN_LOCKOUT_KEY = "admin_login"


def _store():
    return current_app.config["STORE"]


def _build_setup_redirect(chat_id: str) -> str:
    reg_token = _store().create_oauth_session(chat_id)
    return url_for("setup.setup_form") + f"?reg_token={reg_token}"


def _resolve_authenticated_redirect(chat_id: str) -> str:
    """Instrada un utente autenticato verso setup, onboarding o home app."""
    user = _get_user_by_chat_id(chat_id)
    if not user:
        session.clear()
        return url_for("auth.web_login")
    if not _user_has_web_access(user):
        # Account Notion: nessun accesso alla web app, termina la sessione browser.
        session.clear()
        return url_for("auth.web_login")
    if user.setup_completed_at is None:
        return _build_setup_redirect(chat_id)
    if (user.privacy_policy_version_accepted != Config.CURRENT_PRIVACY_POLICY_VERSION
            or user.tos_version_accepted != Config.CURRENT_TOS_VERSION):
        return "/consent"
    if user.onboarding_completed_at is None:
        return "/onboarding"
    return "/home"


@auth_bp.route("/app")
@auth_bp.route("/dashboard")
def web_app_entry():
    """Ingresso pubblico della web app.

    - utente autenticato: porta alla home app Next.js
    - utente anonimo: porta al login Flask
    """
    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(_resolve_authenticated_redirect(chat_id))
    return redirect(url_for("auth.web_login"))


def _safe_next_url(raw_next: str | None) -> str | None:
    """Valida il parametro `next` per evitare open redirect.

    Accetta solo path relativi interni (`/reports`, non URL assoluti né
    protocol-relative `//host/...`, che un attaccante potrebbe usare per
    reindirizzare l'utente autenticato verso un sito esterno).
    """
    if not raw_next:
        return None
    if raw_next.startswith("/") and not raw_next.startswith("//"):
        return raw_next
    return None


def _authenticated_redirect_or_next(chat_id: str, next_url: str | None) -> str:
    """Risolve la destinazione post-login, onorando `next_url` solo a gate superati.

    Un `next_url` (es. dai link "Vai ai report" nelle email di lifecycle) non deve
    scavalcare setup/consenso/onboarding: si applica solo se l'utente ha già superato
    tutti i gate (`_resolve_authenticated_redirect` risolverebbe comunque su `/home`).
    """
    resolved = _resolve_authenticated_redirect(chat_id)
    if resolved == "/home" and next_url:
        return next_url
    return resolved


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def web_login():
    """Login web con email e password.

    Supporta `?next=/percorso` per riportare l'utente a una pagina specifica dopo il
    login (es. il link "Vai ai report" nelle email di lifecycle trial).
    """
    store = _store()
    next_url = _safe_next_url(request.args.get("next") or request.form.get("next"))

    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(_authenticated_redirect_or_next(chat_id, next_url))

    error = None
    if request.method == "POST":
        from src.rate_limiter import (
            get_failed_login_count, track_failed_login, reset_failed_logins,
        )

        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        if get_failed_login_count(email, ACCOUNT_LOCKOUT_WINDOW_SECONDS) >= ACCOUNT_LOCKOUT_THRESHOLD:
            logger.warning(
                "login_locked_out",
                extra={"domain": "security", "event": "login_locked_out",
                       "meta": {"ip": request.remote_addr}},
            )
            return render_template(
                "login.html",
                error="Troppi tentativi falliti. Riprova tra qualche minuto.",
                registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
            )

        user = store.verify_password(email, password)
        if not user:
            user = store.verify_password_any_status(email, password)
            if user:
                store.reactivate_user(user.chat_id)
        if user:
            reset_failed_logins(email)
            if user.registration_status == "pending_verification":
                return render_template(
                    "login.html",
                    error="Controlla la tua email per verificare l'account prima di accedere.",
                    registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
                    next_url=next_url,
                )
            if not _user_has_web_access(user):
                # Account collegato a Notion: la web app non è disponibile.
                return render_template(
                    "login.html",
                    error="Questo account è collegato a Notion: gestisci le tue finanze "
                          "dal bot Telegram e dal tuo workspace Notion. La web app è "
                          "riservata agli account con DB interno.",
                    registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
                    next_url=next_url,
                )
            # "Ricordami": sessione persistente (sopravvive alla chiusura del
            # browser); altrimenti cookie di sessione che muore alla chiusura.
            session.permanent = bool(request.form.get("remember"))
            session["user_logged_in"] = True
            session["chat_id"] = user.chat_id
            session["token_version"] = user.token_version or 0
            try:
                applied = store.apply_pending_referral_rewards(email)
                if applied:
                    threading.Thread(
                        target=_send_referral_reward_emails,
                        args=(applied, None),
                        daemon=True,
                    ).start()
            except Exception:
                logger.exception(
                    "Errore applicazione reward referral pendenti al login",
                    extra={"domain": "dashboard", "event": "referral_reward_apply_failed"},
                )
            return redirect(_authenticated_redirect_or_next(user.chat_id, next_url))

        error = "Email o password errati."
        failed_count = track_failed_login(email)
        logger.warning(
            "user_login_failed",
            extra={"domain": "security", "event": "user_login_failed",
                   "meta": {"failed_attempts": failed_count, "ip": request.remote_addr}},
        )
        if failed_count >= 5:
            store.write_audit_log(
                email or "unknown", actor="system", action="breach_detection",
                metadata={"reason": "repeated_failed_login", "failed_attempts": failed_count},
                ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
            )
            logger.warning(
                "repeated_failed_login",
                extra={"domain": "security", "event": "repeated_failed_login",
                       "meta": {"failed_attempts": failed_count, "ip": request.remote_addr}},
            )
            # Notifica in-app all'utente reale (non all'attaccante): affianca il log
            # di sicurezza, non lo sostituisce, per non perdere copertura se l'utente
            # non apre la webapp. Dedup sulla finestra di lockout: senza, ogni
            # tentativo dal quinto in poi crea una riga — un attaccante che conosce
            # l'email di un utente potrebbe altrimenti sommergerlo di notifiche.
            try:
                target_user = store.get_user_by_email_any_status(email)
                if target_user:
                    with store.Session() as notif_session:
                        window_start = datetime.utcnow() - timedelta(seconds=ACCOUNT_LOCKOUT_WINDOW_SECONDS)
                        already_notified = (
                            notif_session.query(Notification)
                            .filter(
                                Notification.user_id == target_user.chat_id,
                                Notification.type == "security_anomaly",
                                Notification.created_at > window_start,
                            )
                            .first()
                        )
                        if not already_notified:
                            create_notification(
                                notif_session, target_user.chat_id, "security_anomaly",
                                title="Tentativi di accesso sospetti",
                                body="Abbiamo rilevato più tentativi di accesso falliti sul tuo account. "
                                     "Se non sei stato tu, valuta di cambiare la password.",
                                priority="critical",
                            )
            except Exception as sec_notif_err:
                logger.error(
                    "Notifica in-app anomalia sicurezza fallita: %s", type(sec_notif_err).__name__,
                    extra={"domain": "security", "event": "security_notification_failed"},
                )

    return render_template(
        "login.html", error=error, registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
        next_url=next_url,
    )


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def web_register():
    """Registrazione web con prenotazione beta e verifica obbligatoria dell'email."""
    store = _store()
    if not Config.PUBLIC_REGISTRATION_ENABLED:
        return render_template(
            "login.html",
            error="Le registrazioni sono chiuse: siamo in fase beta. "
                  "Controlla la mail che ti abbiamo inviato con le credenziali di accesso.",
        )

    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(_resolve_authenticated_redirect(chat_id))

    referral_code = (request.args.get("ref") or request.form.get("ref") or "").strip()
    if referral_code:
        session["pending_referral_code"] = referral_code[:128]
    else:
        referral_code = session.get("pending_referral_code")

    if request.method == "GET":
        return render_template("register.html", error=None, referral_code=referral_code)

    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""
    privacy_accepted = request.form.get("privacy_accepted") == "on"
    tos_accepted = request.form.get("tos_accepted") == "on"
    age_attested = request.form.get("age_attested") == "on"

    def _err(msg: str):
        return render_template("register.html", error=msg, referral_code=referral_code)

    if not first_name or not last_name:
        return _err("Inserisci nome e cognome.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _err("Email non valida.")
    if len(password) < 8:
        return _err("La password deve essere di almeno 8 caratteri.")
    if password != password_confirm:
        return _err("Le password non coincidono.")
    if not privacy_accepted or not tos_accepted or not age_attested:
        return _err("Devi accettare privacy, termini e attestare di avere almeno 18 anni.")

    try:
        pending = RegistrationService(store).reserve(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            mandatory_consents={
                "privacy_policy_version": Config.CURRENT_PRIVACY_POLICY_VERSION,
                "tos_version": Config.CURRENT_TOS_VERSION,
                "age_attestation": True,
            },
            referral_code=referral_code,
        )
    except RegistrationCapacityReached:
        return _err("La beta è temporaneamente completa. Riprova più avanti.")
    except RegistrationEmailExists:
        return _err("Se l'indirizzo è già registrato, controlla la casella email per accedere.")
    except ValueError as exc:
        return _err(str(exc))
    except Exception:
        logger.exception(
            "Errore registrazione web",
            extra={"domain": "security", "event": "registration_failed"},
        )
        return _err("Errore durante la registrazione. Riprova.")

    try:
        brevo_client.send_verification_email(email, pending.raw_token)
    except Exception:
        logger.exception(
            "Errore invio verifica registrazione",
            extra={"domain": "security", "event": "verification_email_failed"},
        )
    session.pop("pending_referral_code", None)
    analytics.track(
        pending.user.chat_id,
        "user_registration_started",
        {"auth_method": "web", "platform": "web"},
    )
    return redirect(url_for("auth.check_email"))


@auth_bp.route("/check-email", methods=["GET"])
def check_email():
    """Show the neutral post-registration email-check screen."""
    return render_template("check_email.html")


@auth_bp.route("/verify-email", methods=["GET"])
@limiter.limit("20 per minute")
def verify_email():
    """Consume a verification token and start the authenticated onboarding flow."""
    token = request.args.get("token", "")
    user = RegistrationService(_store()).activate(token) if token else None
    if user is None:
        return render_template(
            "verification_result.html",
            success=False,
            message="Il link non è valido o è già scaduto.",
        ), 400
    session.permanent = True
    session["user_logged_in"] = True
    session["chat_id"] = user.chat_id
    session["token_version"] = user.token_version or 0
    return redirect("/onboarding")


@auth_bp.route("/verify-email/resend", methods=["POST"])
@limiter.limit("5 per minute")
def resend_verification_email():
    """Resend a verification link with a response that does not enumerate emails."""
    email = (request.form.get("email") or "").strip().casefold()
    user = _store().get_user_by_email_any_status(email) if email else None
    if user and user.registration_status == "pending_verification":
        try:
            raw_token = issue_auth_token(
                _store(), user.chat_id, "email_verification", timedelta(hours=24)
            )
            brevo_client.send_verification_email(email, raw_token)
        except Exception:
            logger.exception(
                "Errore reinvio verifica registrazione",
                extra={"domain": "security", "event": "verification_resend_failed"},
            )
    return redirect(url_for("auth.check_email"))


@auth_bp.route("/privacy")
def privacy_policy():
    """Redirect all'unica Privacy Policy ufficiale (sito Next.js).

    In passato questa route serviva un template Flask duplicato
    (templates/privacy.html), disallineato dal contenuto reale del prodotto
    (mancavano sub-processor come Tally/Brevo, età minima sbagliata, ecc.).
    Mantenere due informative separate le fa inevitabilmente divergere:
    un solo documento, aggiornato in un solo posto.
    """
    return redirect(f"{Config.WEBAPP_BASE_URL}/it/privacy")


@auth_bp.route("/terms")
def terms_of_service():
    """Redirect ai Termini di Servizio ufficiali (sito Next.js), stesso pattern di /privacy."""
    return redirect(f"{Config.WEBAPP_BASE_URL}/it/terms")


@auth_bp.route("/logout")
def web_logout():
    """Logout web."""
    session.clear()
    return redirect(url_for("auth.web_login"))


# --- Rotte Web (UI) ---
# NB: get_system_metrics() e le route /admin di dashboard sono state estratte nel
# blueprint src/dashboard/admin_routes.py (registrato più in basso). Qui restano
# solo login/logout admin, accanto al rate limiter e all'audit log.

@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    store = _store()
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.index"))

    error = None
    if request.method == "POST":
        from src.rate_limiter import (
            get_failed_login_count, track_failed_login, reset_failed_logins,
        )

        if get_failed_login_count(ADMIN_LOCKOUT_KEY, ACCOUNT_LOCKOUT_WINDOW_SECONDS) >= ACCOUNT_LOCKOUT_THRESHOLD:
            logger.warning(
                "admin_login_locked_out",
                extra={"domain": "security", "event": "admin_login_locked_out",
                       "meta": {"ip": request.remote_addr}},
            )
            return render_template(
                "login.html", admin_mode=True,
                error="Troppi tentativi falliti. Riprova tra qualche minuto.",
            )

        password = request.form.get("password")
        if password == Config.DASHBOARD_PASSWORD:
            reset_failed_logins(ADMIN_LOCKOUT_KEY)
            session["admin_logged_in"] = True
            store.write_audit_log(
                user_id="admin", actor="admin", action="admin_login",
                metadata={"result": "success"},
                ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
            )
            logger.info(
                "admin_login_success",
                extra={"domain": "security", "event": "admin_login_success",
                       "meta": {"ip": request.remote_addr}},
            )
            return redirect(url_for("admin.index"))
        else:
            error = "Password amministratore errata!"
            track_failed_login(ADMIN_LOCKOUT_KEY, ACCOUNT_LOCKOUT_WINDOW_SECONDS)
            store.write_audit_log(
                user_id="admin", actor="admin", action="admin_login",
                metadata={"result": "failure"},
                ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
            )
            logger.warning(
                "admin_login_failed",
                extra={"domain": "security", "event": "admin_login_failed",
                       "meta": {"ip": request.remote_addr}},
            )

    return render_template("login.html", admin_mode=True, error=error)


@auth_bp.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("auth.admin_login"))


# --- ROTTE OAUTH (Fase 2) ---

@auth_bp.route("/auth/notion")
def auth_notion_start():
    """Riceve il registration token e reindirizza a Notion."""
    store = _store()
    reg_token = request.args.get("reg_token")

    if not reg_token:
        return "<h1>Accesso negato</h1><p>Manca il registration token.</p>", 403

    # Verifichiamo che il token esista nel DB (senza cancellarlo ancora!)
    with store.Session() as db_session:
        from src.user_store import OAuthSession
        sess = db_session.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return "<h1>Token non valido o scaduto</h1><p>Riprova la registrazione dal bot.</p>", 403

    # URL di autorizzazione di Notion (usiamo il reg_token come state)
    notion_auth_url = (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?owner=user"
        f"&client_id={Config.NOTION_CLIENT_ID}"
        f"&redirect_uri={Config.NOTION_REDIRECT_URI}"
        f"&response_type=code"
        f"&state={reg_token}"
    )

    return redirect(notion_auth_url)


def _process_oauth_background(
    access_token: str,
    workspace_id: str,
    chat_id: str,
    template_page_id: str | None,
) -> None:
    """Esegue discovery, salvataggio schemi e bootstrap in background.

    Chiamato in un daemon thread dopo che auth_notion_callback ha già
    restituito la risposta HTTP al browser dell'utente.
    """
    store = _store()
    telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"

    def _tg(text: str) -> None:
        try:
            requests.post(
                telegram_url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=TELEGRAM_REQUEST_TIMEOUT,
            )
        except Exception as tg_err:
            logger.exception("[OAuth-bg] Errore invio Telegram: %s", tg_err)

    try:
        import time as _time
        import logging as _logging
        _bg_log = _logging.getLogger("financial_agent.oauth_bg")

        # 1. Auto-Discovery — piccolo delay iniziale per la duplicazione asincrona Notion,
        # poi 1 retry se i DB non vengono trovati tutti al primo tentativo.
        _RETRY_DELAYS = [3, 10]  # secondi di attesa prima di ogni tentativo
        discovered: dict = {}
        all_candidates: list = []
        for _attempt, _delay in enumerate(_RETRY_DELAYS, start=1):
            _bg_log.info(
                "[OAuth-bg] Attesa %ds, poi discovery tentativo %d/%d...",
                _delay, _attempt, len(_RETRY_DELAYS),
            )
            _time.sleep(_delay)
            discovered, all_candidates = NotionFinanceClient.discover_databases(
                access_token, template_page_id=template_page_id
            )
            _bg_log.info("[OAuth-bg] Discovery tentativo %d: %d/7 DB trovati.", _attempt, len(discovered))
            if len(discovered) >= 7:
                break
            if _attempt == len(_RETRY_DELAYS):
                _bg_log.warning("[OAuth-bg] Discovery esaurita dopo %d tentativi: %d/7 DB.", _attempt, len(discovered))

        valid_discovered = discovered

        # 2. Schemi di tutti i DB scoperti
        discovered_schemas = NotionFinanceClient.discover_db_schemas(access_token, valid_discovered)

        # 3. Salviamo utente + database IDs
        store.add_user(
            chat_id=chat_id,
            storage_backend="notion",
            notion_access_token=access_token,
            notion_workspace_id=workspace_id,
            expense_db_id=valid_discovered.get("expense_db_id"),
            income_db_id=valid_discovered.get("income_db_id"),
            categories_db_id=valid_discovered.get("categories_db_id"),
            monthly_balance_db_id=valid_discovered.get("monthly_balance_db_id"),
            accounts_db_id=valid_discovered.get("accounts_db_id"),
            subscriptions_db_id=valid_discovered.get("subscriptions_db_id"),
            pay_transfer_db_id=valid_discovered.get("pay_transfer_db_id"),
        )
        analytics.track(chat_id, "user_signed_up", {"auth_method": "telegram", "storage_backend": "notion", "platform": "telegram"})
        analytics.identify(chat_id, {"auth_method": "telegram", "storage_backend": "notion", "platform": "telegram"})

        # 4. Cache degli schemi
        for db_key, schema_data in discovered_schemas.items():
            try:
                store.save_database_schema(
                    chat_id=chat_id,
                    db_key=db_key,
                    notion_db_id=schema_data.get("database_id"),
                    properties_json=json.dumps(schema_data.get("properties") or {}),
                    mapped_properties_json=json.dumps(schema_data.get("mapped") or {}),
                )
            except Exception as schema_err:
                logger.exception("[OAuth-bg] Errore salvataggio schema %s: %s", db_key, schema_err)

        # 5. Bootstrap workspace (best-effort)
        bootstrap_db_ids = {
            k: valid_discovered[k]
            for k in ("categories_db_id", "accounts_db_id", "subscriptions_db_id")
            if k in valid_discovered
        }
        if len(bootstrap_db_ids) == 3:
            try:
                bootstrap_schemas = {
                    k: discovered_schemas[k]
                    for k in bootstrap_db_ids
                    if k in discovered_schemas
                }
                notion_client_for_bootstrap = NotionFinanceClient(
                    api_key=access_token,
                    categories_db_id=bootstrap_db_ids["categories_db_id"],
                    accounts_db_id=bootstrap_db_ids["accounts_db_id"],
                    subscriptions_db_id=bootstrap_db_ids["subscriptions_db_id"],
                    db_schemas=bootstrap_schemas,
                )
                storage_for_bootstrap = NotionStorage(notion_client_for_bootstrap)
                bootstrap_result = bootstrap_workspace(storage_for_bootstrap)
                if not bootstrap_result.is_empty():
                    bootstrap_msg = bootstrap_result.to_telegram_message()
                    if bootstrap_msg:
                        _tg(bootstrap_msg)
                # Trigger A: prima sincronizzazione categorie → user_categories
                refresh_category_averages(
                    chat_id, store, notion_client=notion_client_for_bootstrap
                )
            except Exception as bootstrap_err:
                logger.exception("[OAuth-bg] Errore bootstrap workspace: %s", bootstrap_err)

        # 6. Notifica finale
        if len(valid_discovered) != 7:
            found_count = len(valid_discovered)

            if found_count == 0:
                # Nessun DB trovato: l'integrazione non ha accesso al template
                report_msg = (
                    "⚠️ <b>Nessun database trovato</b>\n\n"
                    "L'integrazione non riesce a vedere i database del template Expensum.\n\n"
                    "👉 <b>Cosa fare:</b>\n"
                    "1. Apri Notion → cerca la pagina <b>Dashboard Expensum Finance</b>\n"
                    "2. Clicca su <b>...</b> in alto a destra → <b>Connect to</b> → seleziona <b>Expensum Finance Agent</b>\n"
                    "3. Riapri <b>/registrati</b> e riprova\n\n"
                    "<i>Assicurati di condividere la pagina root e tutte le sotto-pagine con l'integrazione.</i>"
                )
            else:
                report_msg = (
                    f"⚠️ <b>Configurazione parziale ({found_count}/7)</b>\n\n"
                    "Ho trovato alcuni database ma ne mancano altri.\n\n"
                    "👉 <b>Cosa fare:</b>\n"
                    "1. Assicurati che nel template ci siano tutti i <b>Database</b> (non solo pagine).\n"
                    "2. Condividi la pagina root <b>Dashboard Expensum Finance</b> con l'integrazione.\n"
                    "3. Riapri <b>/registrati</b> e riprova.\n\n"
                    "<b>Stato verifica:</b>\n"
                )
                for key in [
                    "expense_db_id", "income_db_id", "categories_db_id",
                    "monthly_balance_db_id", "accounts_db_id", "subscriptions_db_id", "pay_transfer_db_id",
                ]:
                    status = "✅" if key in valid_discovered else "❌"
                    name = key.replace("_db_id", "").capitalize()
                    report_msg += f"{status} {name}\n"

                if all_candidates:
                    report_msg += "\n<b>Database accessibili nel tuo workspace:</b>\n"
                    report_msg += ", ".join([f"<i>{c}</i>" for c in all_candidates[:15]])
                    report_msg += (
                        "\n\n<i>Se uno di questi è quello corretto, rinominalo esattamente "
                        "come richiesto (es. 'Expense', 'Income') e riprova.</i>"
                    )

            _tg(report_msg)
            return

        report_msg = "🎊 <b>EXPENSUM È PRONTO!</b>\n\nHo scansionato il tuo Notion e collegato i database:\n"
        if not discovered:
            report_msg += (
                "⚠️ <b>Attenzione</b>: Non ho trovato i database standard (Spese, Entrate, ecc.). "
                "Assicurati di averli creati o rinominati correttamente nel tuo workspace Notion!"
            )
            _tg(report_msg)
        else:
            for key in discovered:
                db_name = key.replace("_db_id", "").capitalize()
                report_msg += f"✅ {db_name}\n"

            # Marca il setup tecnico come completato — l'onboarding delle preferenze
            # avviene nel wizard web/Telegram (non nel setup_miniapp, che resta opzionale)
            store.mark_setup_completed(chat_id)

            report_msg += (
                "\n\n💬 <b>Come registrare le tue spese</b>\n"
                "Scrivimi una spesa in linguaggio naturale, mandami un vocale oppure scattami una "
                "foto dello scontrino: ci penso io ad analizzarla e salvarla automaticamente.\n"
                "Esempi: <i>\"25€ per la spesa al super\"</i>, <i>\"netflix 13.99\"</i>.\n\n"
                "📋 Trovi tutti i comandi disponibili toccando il pulsante <b>Menu</b> in basso a "
                "sinistra, accanto al campo di testo.\n\n"
                "🎉 Ora completa il tuo profilo per personalizzare Expensum!\n"
                "Apri la webapp e segui il wizard di configurazione, oppure scrivi "
                "<b>/impostazioni</b> qui in chat."
            )
            try:
                requests.post(telegram_url, json={
                    "chat_id": chat_id,
                    "text": report_msg,
                    "parse_mode": "HTML",
                }, timeout=TELEGRAM_REQUEST_TIMEOUT)
            except Exception as tg_err:
                logger.exception("[OAuth-bg] Errore invio messaggio finale: %s", tg_err)

    except Exception as e:
        import logging as _logging
        _logging.getLogger("financial_agent.oauth_bg").error(
            "[OAuth-bg] Errore imprevisto nel thread background: %s", e, exc_info=True
        )
        try:
            requests.post(
                telegram_url,
                json={
                    "chat_id": chat_id,
                    "text": "⚠️ Si è verificato un errore durante la configurazione. Riprova con /registrati.",
                    "parse_mode": "HTML",
                },
                timeout=TELEGRAM_REQUEST_TIMEOUT,
            )
        except Exception:
            pass


def _process_postgres_background(chat_id: str) -> None:
    """Bootstrap del backend Postgres: seeda categorie e conti di default, poi notifica Telegram.

    Parallelo a _process_oauth_background ma molto più snello: niente OAuth, niente
    discovery di database, niente schema caching. L'utente viene creato sincronamente
    nel handler; questa funzione fa solo il seed dei default e manda il messaggio.
    """
    store = _store()
    telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"

    def _tg(text: str) -> None:
        try:
            requests.post(
                telegram_url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=TELEGRAM_REQUEST_TIMEOUT,
            )
        except Exception as tg_err:
            logger.exception("[Postgres-bg] Errore invio Telegram: %s", tg_err)

    db_session = None
    try:
        db_session = store.Session()
        storage = PostgresStorage(session=db_session, user_id=chat_id)
        bootstrap_result = bootstrap_workspace(storage)
        # Trigger A: prima sincronizzazione medie categorie per utente Postgres
        refresh_category_averages(chat_id, store, session=db_session)
        store.mark_setup_completed(chat_id)
        analytics.track(chat_id, "user_signed_up", {"auth_method": "telegram", "storage_backend": "postgres", "platform": "telegram"})
        analytics.identify(chat_id, {"auth_method": "telegram", "storage_backend": "postgres", "platform": "telegram"})

        reg_token = store.create_oauth_session(chat_id)
        miniapp_url = f"{Config.WEBAPP_BASE_URL}/setup?reg_token={reg_token}"

        report_msg = (
            "🎊 <b>EXPENSUM È PRONTO!</b>\n\n"
            "Ho creato il tuo spazio personale nel database interno di Expensum.\n"
        )
        bootstrap_msg = bootstrap_result.to_telegram_message()
        if bootstrap_msg:
            report_msg += "\n" + bootstrap_msg

        report_msg += (
            "\n\n👇 <b>Inizia a usare Expensum configurando il tuo spazio:</b>\n"
            "1️⃣ Clicca sul pulsante qui sotto.\n"
            "2️⃣ Aggiungi i tuoi <b>Conti</b> (es. Conto Corrente, Contanti) e imposta il saldo iniziale.\n"
            "3️⃣ Personalizza le tue <b>Categorie</b> di spesa ed eventuali budget.\n"
            "4️⃣ Inserisci i tuoi <b>Abbonamenti</b> per tenerne traccia automaticamente.\n\n"
            "💬 <b>Come registrare le tue spese</b>\n"
            "Scrivimi una spesa in linguaggio naturale, mandami un vocale oppure scattami una "
            "foto dello scontrino: ci penso io ad analizzarla e salvarla automaticamente.\n"
            "Esempi: <i>\"25€ per la spesa al super\"</i>, <i>\"netflix 13.99\"</i>.\n\n"
            "📋 Trovi tutti i comandi disponibili toccando il pulsante <b>Menu</b> in basso a "
            "sinistra, accanto al campo di testo."
        )

        try:
            requests.post(telegram_url, json={
                "chat_id": chat_id,
                "text": report_msg,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[{
                        "text": "⚙️ Configura il tuo spazio",
                        "url": miniapp_url
                    }]]
                }
            }, timeout=TELEGRAM_REQUEST_TIMEOUT)
        except Exception as tg_err:
            logger.exception("[Postgres-bg] Errore invio messaggio finale: %s", tg_err)

    except Exception as e:
        import logging as _logging
        _logging.getLogger("financial_agent.postgres_bg").error(
            "[Postgres-bg] Errore imprevisto nel thread background: %s", e, exc_info=True
        )
        _tg("⚠️ Si è verificato un errore durante la configurazione. Riprova con /registrati.")
    finally:
        if db_session is not None:
            db_session.close()


@auth_bp.route("/auth/postgres", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def auth_postgres_start():
    """Registrazione su PostgreSQL: raccoglie email e password prima di creare l'utente."""
    store = _store()
    reg_token = request.args.get("reg_token") or request.form.get("reg_token")
    if not reg_token:
        return "<h1>Accesso negato</h1><p>Manca il registration token.</p>", 403

    if request.method == "GET":
        return render_template("register_postgres.html", reg_token=reg_token, error=None)

    # POST: valida e crea l'utente
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    privacy_accepted = request.form.get("privacy_accepted") == "on"
    tos_accepted = request.form.get("tos_accepted") == "on"

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template("register_postgres.html", reg_token=reg_token, error="Email non valida.")
    if len(password) < 8:
        return render_template("register_postgres.html", reg_token=reg_token, error="La password deve essere di almeno 8 caratteri.")
    if password != password2:
        return render_template("register_postgres.html", reg_token=reg_token, error="Le password non coincidono.")
    if not privacy_accepted or not tos_accepted:
        return render_template(
            "register_postgres.html", reg_token=reg_token,
            error="Devi accettare privacy policy e termini di servizio per registrarti.",
        )
    if store.get_user_by_email(email):
        return render_template("register_postgres.html", reg_token=reg_token, error="Email già registrata.")

    # Consuma la sessione OAuth (atomico: recupera chat_id e cancella il token)
    chat_id = store.get_and_delete_oauth_session(reg_token)
    if not chat_id:
        return "<h1>Token non valido o scaduto</h1><p>Riprova la registrazione dal bot.</p>", 403

    try:
        store.add_user(chat_id=chat_id, storage_backend="postgres", setup_status="WAIT_ACCOUNTS")
        store.set_credentials(chat_id, email, password)
        store.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
        store.write_audit_log(
            chat_id, actor="user", action="consent_change",
            metadata={"consent_type": "privacy_policy", "version": Config.CURRENT_PRIVACY_POLICY_VERSION},
            ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
        )
        store.accept_terms_of_service(chat_id, Config.CURRENT_TOS_VERSION)
        store.write_audit_log(
            chat_id, actor="user", action="consent_change",
            metadata={"consent_type": "terms_of_service", "version": Config.CURRENT_TOS_VERSION},
            ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
        )
    except Exception as e:
        import logging as _logging
        _logging.getLogger("financial_agent.auth_postgres").error(
            "Errore creazione utente postgres: %s", e, exc_info=True
        )
        return "<h1>Errore imprevisto</h1><p>Riprova dal bot.</p>", 500

    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    "✅ <b>Registrazione completata!</b>\n\n"
                    "Sto preparando il tuo spazio nel database interno.\n"
                    "Tra pochi secondi potrai iniziare. 🚀"
                ),
                "parse_mode": "HTML",
            },
            timeout=TELEGRAM_REQUEST_TIMEOUT,
        )
    except Exception:
        pass

    threading.Thread(target=_process_postgres_background, args=(chat_id,), daemon=True).start()
    return redirect("https://t.me/ExpensumFinanceBot")


@auth_bp.route("/auth/notion/callback")
def auth_notion_callback():
    """Riceve il codice da Notion, scambia il token e avvia il setup in background."""
    store = _store()
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h1>Errore di autorizzazione Notion</h1><p>{escape(error)}</p>"

    if not code or not state:
        return "<h1>Parametri mancanti</h1>", 400

    # 1. Verifica stato OAuth
    chat_id = store.get_and_delete_oauth_session(state)
    if not chat_id:
        logger.warning(
            "oauth_state_invalid",
            extra={"domain": "security", "event": "oauth_state_invalid", "meta": {}},
        )
        return "<h1>Sessione scaduta o non valida</h1><p>Riprova la registrazione dal bot.</p>", 403

    # 2. Scambio CODE -> ACCESS TOKEN (unica operazione sincrona)
    try:
        response = requests.post(
            "https://api.notion.com/v1/oauth/token",
            auth=(Config.NOTION_CLIENT_ID, Config.NOTION_CLIENT_SECRET),
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": Config.NOTION_REDIRECT_URI,
            },
            timeout=TELEGRAM_REQUEST_TIMEOUT,
        )
        if not response.ok:
            logger.warning(
                "oauth_token_exchange_failed",
                extra={"domain": "security", "event": "oauth_token_exchange_failed",
                       "chat_id": chat_id, "meta": {"status_code": response.status_code}},
            )
            return f"<h1>Errore scambio token</h1><p>{escape(response.text)}</p>", 500

        auth_data = response.json()
        access_token = auth_data.get("access_token")
        workspace_id = auth_data.get("workspace_id")
        template_page_id = auth_data.get("duplicated_template_id")
    except Exception as e:
        logger.warning(
            "oauth_token_exchange_failed",
            extra={"domain": "security", "event": "oauth_token_exchange_failed",
                   "chat_id": chat_id, "meta": {"error_type": type(e).__name__}},
        )
        return f"<h1>Errore imprevisto</h1><p>{str(e)}</p>", 500

    # 3. Notifica immediata all'utente e avvio elaborazione in background
    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    "⏳ <b>Autorizzazione ricevuta!</b>\n\n"
                    "Sto configurando il tuo workspace Notion in background "
                    "(discovery database, schemi, dati di default).\n\n"
                    "Riceverai un messaggio qui quando tutto è pronto. Di solito "
                    "ci vogliono meno di 30 secondi. 🚀"
                ),
                "parse_mode": "HTML",
            },
            timeout=TELEGRAM_REQUEST_TIMEOUT,
        )
    except Exception:
        pass  # Non bloccare se Telegram è irraggiungibile

    t = threading.Thread(
        target=_process_oauth_background,
        args=(access_token, workspace_id, chat_id, template_page_id),
        daemon=False,  # NON daemon: il Flask reloader non deve killarlo durante la discovery
    )
    t.start()

    return redirect("https://t.me/ExpensumFinanceBot")


# --- LOGIN MINI APP (Telegram WebApp) ---

@auth_bp.route("/auth/telegram-login", methods=["GET", "POST"])
def telegram_login_miniapp():
    """Form di login ottimizzato per Telegram WebApp. Aperto tramite /accedi nel bot."""
    from src.user_store import OAuthSession

    store = _store()
    state = request.args.get("state") or request.form.get("state", "")

    # Verifica che il token di sessione esista
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=state).first()
        if not sess:
            return render_template("telegram_login.html", expired=True)
        chat_id = sess.chat_id

    if request.method == "GET":
        return render_template("telegram_login.html", state=state)

    # POST: verifica credenziali
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    user = store.verify_password(email, password)
    was_suspended = False
    if not user:
        user = store.verify_password_any_status(email, password)
        if user:
            was_suspended = True
        else:
            return render_template("telegram_login.html", state=state, error="Email o password errati.")

    # Riattiva l'account se era sospeso
    if was_suspended:
        store.reactivate_user(user.chat_id)

    # Gestisce accesso da chat_id diverso (cambio account Telegram). Riassegnazione
    # cross-tenant: arruolata qui (ruolo DML-only), eseguita da
    # scripts/process_reassignment_jobs.py (worker fuori banda, ruolo owner mai esposto
    # a rete). Vedi security design notes § Vulnerabilità residua #2.
    final_chat_id = chat_id
    if user.chat_id != chat_id:
        job_id = store.enqueue_chat_id_reassignment(user.chat_id, chat_id)
        status, error_text = store.wait_for_reassignment_job(job_id)
        if status == "failed":
            return render_template(
                "telegram_login.html",
                state=state,
                error="Questo account Telegram e gia associato a un altro profilo.",
            )
        if status == "pending":
            return render_template(
                "telegram_login.html",
                state=state,
                error="Il collegamento richiede qualche istante in più. Riprova tra poco.",
            )

    # Consuma il token di sessione
    store.get_and_delete_oauth_session(state)

    # Notifica l'utente su Telegram
    msg = "✅ *Account riattivato!* Bentornato." if was_suspended else "✅ *Login effettuato!* Bentornato."
    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": final_chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=TELEGRAM_REQUEST_TIMEOUT,
        )
    except Exception:
        pass

    return render_template("telegram_login.html", success=True)


@auth_bp.route("/api/auth/session", methods=["GET"])
def api_auth_session():
    """Verifica se la richiesta appartiene a un utente autenticato."""
    chat_id, auth_mode = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"authorized": False}), 401

    redirect_to = _resolve_authenticated_redirect(chat_id)
    return jsonify({
        "authorized": True,
        "auth_mode": auth_mode,
        "chat_id": chat_id,
        "redirect_to": None if redirect_to == "/home" else redirect_to,
    })
