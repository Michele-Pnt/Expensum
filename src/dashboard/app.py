import os
import re
import sys
import json
import uuid
import difflib
import logging
import threading
from pathlib import Path
from functools import wraps

logger = logging.getLogger(__name__)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from markupsafe import escape
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import psutil
from datetime import date, datetime, timedelta
import requests
from notion_client import Client as NotionClient

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import Config
from src.user_store import UserStore, User, LlmUsageEvent, LlmPricing, DailyMetrics, Feedback, ChatMessage
from src import analytics
from src import brevo_client
from src import beta_access
from src.privacy_export import build_export_json, build_csv_rows, CSV_HEADER, NOTION_CSV_UNAVAILABLE_MESSAGE
from src.notion_client import NotionFinanceClient
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.workspace_bootstrapper import bootstrap_workspace, bootstrap_lifestyle_categories
from src.category_sync import refresh_category_averages
from src.dashboard_message import build_dashboard_text

# Inizializza l'app Flask
# static_url_path sotto /admin: nginx proxya a Flask solo /admin, /auth e
# /api (vedi deployment documentation) — lo static_url_path di default "/static" cade
# fuori da questi prefissi e finisce sul frontend Next.js (404), lasciando
# la dashboard admin senza CSS. Solo i template della dashboard (base.html)
# referenziano static/, quindi spostarlo sotto /admin/static non tocca le
# altre pagine Flask (login, register, ecc. sono self-contained).
app = Flask(__name__, static_url_path="/admin/static")
# Dietro nginx: senza questo, Werkzeug costruisce URL assoluti di redirect
# (es. lo strict-slash redirect di /admin -> /admin/) usando l'host visto
# a livello di socket (127.0.0.1:5000) invece del dominio pubblico dietro
# il reverse proxy, facendo puntare il browser a un indirizzo irraggiungibile.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
_flask_secret = os.getenv("FLASK_SECRET_KEY")
if not _flask_secret:
    raise RuntimeError(
        "FLASK_SECRET_KEY non impostata. L'app richiede una secret key "
        "persistente per firmare i cookie di sessione. Genera con "
        "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
        "e aggiungila al .env."
    )
app.secret_key = _flask_secret
app.config['WTF_CSRF_CHECK_DEFAULT'] = False   # CSRF applicato solo ai form, non alle JSON API
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # blocca invio cookie su richieste cross-origin
app.config['SESSION_COOKIE_HTTPONLY'] = True    # cookie non accessibile da JavaScript
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'  # HTTPS only in prod
# "Ricordami": una sessione marcata permanente (session.permanent = True) sopravvive
# alla chiusura del browser fino a PERMANENT_SESSION_LIFETIME. Con REFRESH_EACH_REQUEST
# la scadenza è *scorrevole*: ogni richiesta la sposta avanti di 30 giorni, quindi
# l'utente resta loggato finché torna almeno una volta ogni 30 giorni. Senza spuntare
# "ricordami" la sessione resta un cookie di sessione del browser (muore alla chiusura).
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
csrf = CSRFProtect(app)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=[])

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


@app.before_request
def enforce_csrf_on_forms():
    """Applica CSRF ai form HTML e alle API autenticate via cookie di sessione browser.

    Le richieste /api/* che portano l'header X-Telegram-Init-Data sono esenti:
    un sito malevolo non può impostare header custom su richieste cross-origin,
    quindi quel canale di autenticazione non è sfruttabile da CSRF. Quando invece
    la stessa pagina viene aperta in un browser normale (fuori dalla WebView
    Telegram), l'header manca e l'autenticazione ricade sul cookie di sessione,
    che torna vulnerabile esattamente come le rotte protette dai form HTML.
    """
    if not app.config.get("WTF_CSRF_ENABLED", True):
        # Rispetta il flag standard Flask-WTF: protect() chiamato manualmente
        # (come qui sotto) non lo controlla di suo, a differenza dell'hook
        # automatico di CSRFProtect. Senza questo check, WTF_CSRF_ENABLED=False
        # nei test è inerte e ogni POST richiede comunque un token valido.
        return
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if request.path == "/auth/telegram-login":
        return
    if request.path.startswith("/api/") and request.headers.get("X-Telegram-Init-Data"):
        return
    if request.path.startswith("/webhooks/"):
        # Chiamate server-to-server (Tally, ecc.), non autenticate via cookie di
        # sessione browser: la protezione CSRF non si applica per definizione.
        return
    csrf.protect()


@app.route("/api/csrf-token", methods=["GET"])
def api_csrf_token():
    """Restituisce un token CSRF per la sessione browser corrente.

    Usato dalle pagine Next.js che non possono leggere {{ csrf_token() }} via Jinja.
    """
    return jsonify({"csrf_token": generate_csrf()})

_TRACK_EVENT_RE = re.compile(r"^[a-z0-9_]{1,64}$")


@app.route("/api/track", methods=["POST"])
@limiter.limit("60 per minute")
def api_track():
    """Riceve un evento di analytics dal frontend e lo inoltra server-side.

    Il browser non parla mai direttamente con PostHog/GA4/Meta: questa rotta
    è same-origin, quindi la CSP non deve concedere script-src/connect-src a
    nessuno di quei domini. Il consenso cookie (letto lato client dal CMP)
    decide quali vendor vengono effettivamente notificati. PostHog è nella
    categoria "analytics" del banner esattamente come GA4 (vedi
    CookieConsent.tsx) e va quindi gated allo stesso modo — non è esente dal
    consenso solo perché la chiamata è server-side.
    """
    data = request.get_json(silent=True) or {}
    event = data.get("event", "")
    if not _TRACK_EVENT_RE.match(event):
        return jsonify({"error": "invalid event name"}), 400

    properties = data.get("properties") or {}
    if not isinstance(properties, dict):
        return jsonify({"error": "invalid properties"}), 400

    anonymous_id = data.get("anonymous_id")
    session_chat_id = _get_session_chat_id()
    distinct_id = session_chat_id or anonymous_id
    if not distinct_id or not isinstance(distinct_id, str) or len(distinct_id) > 128:
        return jsonify({"error": "missing distinct id"}), 400

    consent = data.get("consent") or {}
    if consent.get("analytics"):
        if event == "identify":
            analytics.identify(distinct_id, properties)
            return jsonify({"ok": True})
        analytics.track(distinct_id, event, properties)
        analytics.track_ga4(distinct_id, event, properties)
        # Il tour guidato webapp prima viveva solo in localStorage: questi eventi
        # rispecchiano lo stato in Postgres (solo per sessioni autenticate, mai
        # per visitatori anonimi) così la dashboard admin sa chi lo salta e a
        # quale step si ferma. Vedi frontend/src/context/TourContext.tsx.
        if session_chat_id and event.startswith("tour_"):
            store.record_tour_event(session_chat_id, event, properties.get("step_id"))
    if consent.get("marketing"):
        event_id = data.get("event_id") or str(uuid.uuid4())
        analytics.track_meta(event, event_id, properties)

    return jsonify({"ok": True})


# --- Webhooks marketing ---

def _extract_tally_email(fields: list) -> str | None:
    """Estrae l'email dai campi di un submit Tally (per tipo o label)."""
    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("type") == "INPUT_EMAIL":
            value = field.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = (field.get("label") or "").strip().lower()
        value = field.get("value")
        if "email" in label and isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _extract_tally_name(fields: list) -> str:
    """Estrae il nome dai campi di un submit Tally (per label), stringa vuota se assente."""
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = (field.get("label") or "").strip().lower()
        value = field.get("value")
        if "nome" in label and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _sync_tally_lead_to_brevo(tally_submission_id: str, email: str, name: str = "") -> None:
    """Sincronizza un lead Tally su Brevo e, se sotto il tetto configurato,
    crea subito l'account beta e invia le credenziali (in background: risponde
    subito 200 a Tally, che ha timeout stretti sul webhook, senza far dipendere
    l'ack dalla latenza di Brevo).
    """
    try:
        brevo_client.upsert_contact(email, list_ids=[Config.BREVO_BETA_WAITLIST_LIST_ID])
        store.mark_tally_lead_synced(tally_submission_id)
    except Exception:
        logger.exception(
            "Errore sync lead Tally verso Brevo",
            extra={"domain": "dashboard", "event": "tally_brevo_sync_failed"},
        )

    if not Config.AUTO_BETA_ACCESS_ENABLED:
        return

    try:
        if store.count_beta_accounts_granted() >= Config.AUTO_BETA_ACCESS_MAX_ACCOUNTS:
            logger.warning(
                "Tetto account beta automatici raggiunto, nessuna creazione",
                extra={"domain": "dashboard", "event": "beta_access_cap_reached"},
            )
            return
        granted = beta_access.grant_beta_access(store, email, name)
        if granted:
            store.mark_tally_lead_beta_access_granted(tally_submission_id)
            logger.info(
                "Account beta creato automaticamente da lead Tally",
                extra={"domain": "dashboard", "event": "beta_access_auto_granted"},
            )
    except Exception:
        logger.exception(
            "Errore creazione account beta automatica",
            extra={"domain": "dashboard", "event": "beta_access_auto_failed"},
        )


@app.route("/webhooks/tally", methods=["POST"])
@limiter.limit("60 per minute")
def webhook_tally():
    """Riceve i submit del form Tally (waitlist beta) e sincronizza il lead su Brevo.

    Chiamata server-to-server da Tally, non autenticata via cookie di sessione
    (vedi carve-out in enforce_csrf_on_forms). Idempotente su submissionId:
    i retry del webhook Tally non generano doppie righe né doppi sync.
    """
    payload = request.get_json(silent=True) or {}
    data = payload.get("data") or {}
    submission_id = data.get("submissionId")
    if not submission_id or not isinstance(submission_id, str):
        return jsonify({"error": "missing submissionId"}), 400

    fields = data.get("fields") or []
    email = _extract_tally_email(fields) if isinstance(fields, list) else None
    name = _extract_tally_name(fields) if isinstance(fields, list) else ""

    lead, is_new = store.save_tally_lead(
        tally_submission_id=submission_id,
        email=email,
        raw_payload=json.dumps(payload),
    )

    logger.info(
        "Lead Tally ricevuto",
        extra={
            "domain": "dashboard",
            "event": "tally_lead_received",
            "meta": {"is_new": is_new, "has_email": bool(email)},
        },
    )

    if is_new and email:
        threading.Thread(
            target=_sync_tally_lead_to_brevo,
            args=(submission_id, email, name),
            daemon=True,
        ).start()

    return jsonify({"ok": True})


@app.after_request
def skip_ngrok_interstitial(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

# Inizializza la connessione allo storage SQLite
# pool piccolo apposta: dashboard admin, max 2 sessioni concorrenti reali (i due
# cofounder) — vedi analisi 2026-07-16, il pool va condiviso col bot su max_connections=30
store = UserStore(db_url=Config.DATABASE_URL, pool_size=3, max_overflow=2)

# Dashboard admin: le route /admin/* vivono nel blueprint admin_bp, che legge lo
# store condiviso da app.config["STORE"] (nessun import di app.py → nessun ciclo).
app.config["STORE"] = store
from src.dashboard.admin_routes import admin_bp  # noqa: E402
app.register_blueprint(admin_bp)


@app.route("/unsubscribe", methods=["GET"])
def unsubscribe():
    """Disattiva le notifiche (Telegram + email) senza richiedere login.

    Il link viene inviato nelle email di lifecycle/marketing (drip trial) con un token
    firmato sul chat_id, verificabile da chiunque riceva l'email ma non falsificabile.
    """
    from src.unsubscribe_token import verify_unsubscribe_token

    chat_id = request.args.get("chat_id", "").strip()
    token = request.args.get("token", "").strip()
    if not chat_id or not token:
        return jsonify({"error": "missing chat_id or token"}), 400

    if not verify_unsubscribe_token(chat_id, token, app.secret_key):
        return jsonify({"error": "invalid token"}), 403

    _set_notifications_enabled(chat_id, False)

    logger.info(
        "Utente disiscritto dalle notifiche via link email",
        extra={"domain": "dashboard", "event": "unsubscribe_via_email_link"},
    )
    return "Notifiche disattivate. Puoi riattivarle in qualsiasi momento dalle impostazioni.", 200


def _set_notifications_enabled(chat_id: str, enabled: bool) -> None:
    """Aggiorna il flag notifications_enabled per chat_id (usato da /unsubscribe)."""
    with store.Session() as session:
        user = session.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return
        user.notifications_enabled = enabled
        session.commit()


@app.route("/webhooks/stripe", methods=["POST"])
def webhook_stripe():
    """Stub webhook Stripe — scaffolding inerte finché non si esce dalla beta.

    Nessuna verifica firma né logica di business qui: risponde 503 finché
    STRIPE_API_KEY non è configurata. La vera integrazione (Checkout Session,
    verifica firma webhook, wiring set_user_plan) è tracciata come task separato.
    """
    if not Config.STRIPE_API_KEY:
        logger.info(
            "Webhook Stripe ricevuto ma non ancora attivo (beta mode)",
            extra={"domain": "dashboard", "event": "stripe_webhook_disabled"},
        )
        return jsonify({"error": "not_available_yet"}), 503

    # TODO: verifica firma webhook + gestione eventi (post-beta, task pagamenti Stripe)
    return jsonify({"error": "not_implemented"}), 501


def _get_session_chat_id() -> str | None:
    """Ritorna il chat_id della sessione browser se valida.

    Oltre al flag di login, verifica la `token_version`: il valore salvato nel
    cookie al login deve combaciare con quello corrente nel DB. In caso contrario
    la sessione è stata revocata (cambio password, "esci da tutti i dispositivi")
    o è una sessione legacy anteriore all'introduzione del meccanismo: in entrambi
    i casi va invalidata forzando un nuovo login.
    """
    if not session.get("user_logged_in"):
        return None
    chat_id = session.get("chat_id")
    if not chat_id:
        return None
    current_version = store.get_token_version(chat_id)
    if current_version is None or session.get("token_version") != current_version:
        session.clear()
        return None
    return str(chat_id)


def _get_user_by_chat_id(chat_id: str):
    from src.user_store import User

    with store.Session() as s:
        return s.query(User).filter_by(chat_id=chat_id).first()


def _user_has_web_access(user) -> bool:
    """La web app è riservata agli utenti con backend PostgreSQL.

    Chi ha collegato Notion gestisce le finanze esclusivamente dal bot Telegram
    e dal proprio workspace Notion: per questi utenti la web app (login browser,
    chat, onboarding, analytics, gestione spazi, impostazioni) non è disponibile.
    """
    return bool(user) and user.storage_backend != "notion"


def _build_setup_redirect(chat_id: str) -> str:
    reg_token = store.create_oauth_session(chat_id)
    return url_for("setup_form") + f"?reg_token={reg_token}"


def _resolve_authenticated_redirect(chat_id: str) -> str:
    """Instrada un utente autenticato verso setup, onboarding o home app."""
    user = _get_user_by_chat_id(chat_id)
    if not user:
        session.clear()
        return url_for("web_login")
    if not _user_has_web_access(user):
        # Account Notion: nessun accesso alla web app, termina la sessione browser.
        session.clear()
        return url_for("web_login")
    if user.setup_completed_at is None:
        return _build_setup_redirect(chat_id)
    if user.onboarding_completed_at is None:
        return "/onboarding"
    return "/chat"


def _resolve_request_chat_id() -> tuple[str | None, str | None]:
    """Risolvi utente autenticato via Telegram WebApp o sessione browser."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        parsed = _validate_telegram_init_data(init_data)
        if parsed and parsed.get("chat_id"):
            chat_id = str(parsed["chat_id"])
            # Gli utenti Notion non hanno accesso alla web app: nega la risoluzione
            # così ogni endpoint risponde 401 anche via Telegram WebApp.
            if not _user_has_web_access(_get_user_by_chat_id(chat_id)):
                return None, None
            return chat_id, "telegram"

    chat_id = _get_session_chat_id()
    if not chat_id:
        return None, None

    user = _get_user_by_chat_id(chat_id)
    if not user:
        session.clear()
        return None, None
    if not _user_has_web_access(user):
        return None, None
    return chat_id, "browser"


def _forbidden_setup_response():
    return "<h1>Accesso negato</h1><p>Link non valido o sessione non autorizzata.</p>", 403


def _resync_category_cache_from_notion(user: "User") -> None:
    """Riallinea la cache `user_categories` a Notion dopo una mutazione categoria.

    Per gli utenti Notion, create/rename/delete di categorie dalla web app scrivono
    solo su Notion: senza questo re-sync la cache (che alimenta il parser del bot)
    resterebbe disallineata fino al job notturno. Best-effort: la scrittura su Notion
    è già avvenuta, quindi eventuali errori qui vengono solo loggati.
    """
    if user.storage_backend != "notion" or not user.categories_db_id:
        return
    try:
        from src.category_sync import sync_categories_to_local

        notion_client = NotionFinanceClient(
            api_key=user.notion_access_token,
            categories_db_id=user.categories_db_id,
        )
        sync_categories_to_local(notion_client, user.chat_id, store)
    except Exception as e:
        logger.warning(
            "[Manage] Re-sync cache categorie fallito per %s: %s", user.chat_id, e
        )


def _trigger_dashboard_refresh(user: "User", s) -> None:
    """Aggiorna il messaggio dashboard pinnato dopo una modifica da web app.

    Best-effort: gli errori vengono loggati ma non propagati al caller.
    Chiamata dopo add/update/remove di abbonamenti, conti e categorie.
    """
    try:
        msg_id = store.get_pinned_dashboard_msg_id(user.chat_id)
        if not msg_id:
            return

        if user.storage_backend == "postgres":
            pg = PostgresStorage(session=s, user_id=user.chat_id)
            accounts = pg.fetch_accounts()
            subscriptions = pg.fetch_subscriptions()
        else:
            notion_client = NotionFinanceClient(
                api_key=user.notion_access_token,
                accounts_db_id=user.accounts_db_id,
                subscriptions_db_id=user.subscriptions_db_id,
                categories_db_id=user.categories_db_id,
            )
            storage = NotionStorage(notion_client, store=store, user_id=user.chat_id)
            accounts = storage.fetch_accounts()
            subscriptions = storage.fetch_subscriptions()

        plan = store.get_user_plan(user.chat_id)
        is_premium = plan.get("plan_type") == "pro"

        dashboard_text = build_dashboard_text(
            accounts=accounts,
            subscriptions=subscriptions,
            is_premium=is_premium,
            user_plan=plan,
        )

        payload: dict = {
            "chat_id": int(user.chat_id),
            "message_id": msg_id,
            "text": dashboard_text,
            "parse_mode": "Markdown",
        }
        if is_premium:
            payload["reply_markup"] = {
                "inline_keyboard": [[{
                    "text": "📊 Apri Analytics",
                    "web_app": {"url": f"{Config.WEBAPP_BASE_URL}/analytics"},
                }]]
            }

        resp = requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/editMessageText",
            json=payload,
            timeout=5,
        )
        if not resp.ok and "message is not modified" not in resp.text:
            logger.warning("Telegram editMessageText failed: %s", resp.text)
    except Exception:
        logger.exception("Errore nel refresh dashboard dopo modifica web app (user=%s)", user.chat_id)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # _get_session_chat_id valida anche la token_version: una sessione revocata
        # viene azzerata qui e reindirizzata al login.
        if not _get_session_chat_id():
            return redirect(url_for("web_login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/app")
@app.route("/dashboard")
def web_app_entry():
    """Ingresso pubblico della web app.

    - utente autenticato: porta alla home app Next.js
    - utente anonimo: porta al login Flask
    """
    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(_resolve_authenticated_redirect(chat_id))
    return redirect(url_for("web_login"))


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


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def web_login():
    """Login web con email e password.

    Supporta `?next=/percorso` per riportare l'utente a una pagina specifica dopo il
    login (es. il link "Vai ai report" nelle email di lifecycle trial).
    """
    next_url = _safe_next_url(request.args.get("next") or request.form.get("next"))

    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(next_url or _resolve_authenticated_redirect(chat_id))

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
            if not _user_has_web_access(user):
                # Account collegato a Notion: la web app non è disponibile.
                return render_template(
                    "login.html",
                    error="Questo account è collegato a Notion: gestisci le tue finanze "
                          "dal bot Telegram e dal tuo workspace Notion. La web app è "
                          "riservata agli account con backend PostgreSQL.",
                    registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
                    next_url=next_url,
                )
            # "Ricordami": sessione persistente (sopravvive alla chiusura del
            # browser); altrimenti cookie di sessione che muore alla chiusura.
            session.permanent = bool(request.form.get("remember"))
            session["user_logged_in"] = True
            session["chat_id"] = user.chat_id
            session["token_version"] = user.token_version or 0
            return redirect(next_url or _resolve_authenticated_redirect(user.chat_id))

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

    return render_template(
        "login.html", error=error, registration_enabled=Config.PUBLIC_REGISTRATION_ENABLED,
        next_url=next_url,
    )


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def web_register():
    """Registrazione web: crea un account senza passare da Telegram.

    Disattivata in fase beta (Config.PUBLIC_REGISTRATION_ENABLED=False): gli
    account vengono creati manualmente via administrative provisioning e le
    credenziali inviate via email, per limitare l'accesso ai soli beta tester.
    """
    if not Config.PUBLIC_REGISTRATION_ENABLED:
        return render_template(
            "login.html",
            error="Le registrazioni sono chiuse: siamo in fase beta. "
                  "Controlla la mail che ti abbiamo inviato con le credenziali di accesso.",
        )

    chat_id = _get_session_chat_id()
    if chat_id:
        return redirect(_resolve_authenticated_redirect(chat_id))

    if request.method == "GET":
        return render_template("register.html", error=None)

    import re
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""

    def _err(msg: str):
        return render_template("register.html", error=msg)

    if not first_name or not last_name:
        return _err("Inserisci nome e cognome.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _err("Email non valida.")
    if len(password) < 8:
        return _err("La password deve essere di almeno 8 caratteri.")
    if password != password_confirm:
        return _err("Le password non coincidono.")
    if store.get_user_by_email(email):
        return _err("Email già registrata.")

    web_chat_id = f"web_{uuid.uuid4().hex}"
    try:
        store.add_user(
            chat_id=web_chat_id,
            storage_backend="postgres",
            setup_status="COMPLETED",
            setup_completed_at=datetime.utcnow(),
            username=f"{first_name} {last_name}",
            is_active=True,
        )
        store.set_credentials(web_chat_id, email, password)
        store.accept_privacy_policy(web_chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
        store.write_audit_log(
            web_chat_id, actor="user", action="consent_change",
            metadata={"consent_type": "privacy_policy", "version": Config.CURRENT_PRIVACY_POLICY_VERSION},
            ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
        )
    except Exception:
        logger.exception("Errore registrazione web per email=%s", email)
        return _err("Errore durante la registrazione. Riprova.")

    analytics.track(web_chat_id, "user_signed_up", {"auth_method": "web", "storage_backend": "postgres"})
    # Appena registrato: sessione persistente, così non deve rifare login subito.
    session.permanent = True
    session["user_logged_in"] = True
    session["chat_id"] = web_chat_id
    session["token_version"] = 0
    return redirect("/onboarding")


@app.route("/privacy")
def privacy_policy():
    """Redirect all'unica Privacy Policy ufficiale (sito Next.js).

    In passato questa route serviva un template Flask duplicato
    (templates/privacy.html), disallineato dal contenuto reale del prodotto
    (mancavano sub-processor come Tally/Brevo, età minima sbagliata, ecc.).
    Mantenere due informative separate le fa inevitabilmente divergere:
    un solo documento, aggiornato in un solo posto.
    """
    return redirect(f"{Config.WEBAPP_BASE_URL}/it/privacy")


@app.route("/logout")
def web_logout():
    """Logout web."""
    session.clear()
    return redirect(url_for("web_login"))


# --- Rotte Web (UI) ---
# NB: get_system_metrics() e le route /admin di dashboard sono state estratte nel
# blueprint src/dashboard/admin_routes.py (registrato più in basso). Qui restano
# solo login/logout admin, accanto al rate limiter e all'audit log.

ADMIN_LOCKOUT_KEY = "admin_login"


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
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

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# --- ROTTE OAUTH (Fase 2) ---

@app.route("/auth/notion")
def auth_notion_start():
    """Riceve il registration token e reindirizza a Notion."""
    reg_token = request.args.get("reg_token")
    
    if not reg_token:
        return "<h1>Accesso negato</h1><p>Manca il registration token.</p>", 403
        
    # Verifichiamo che il token esista nel DB (senza cancellarlo ancora!)
    with store.Session() as session:
        from src.user_store import OAuthSession
        sess = session.query(OAuthSession).filter_by(state=reg_token).first()
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

    session = None
    try:
        session = store.Session()
        storage = PostgresStorage(session=session, user_id=chat_id)
        bootstrap_result = bootstrap_workspace(storage)
        # Trigger A: prima sincronizzazione medie categorie per utente Postgres
        refresh_category_averages(chat_id, store, session=session)
        store.mark_setup_completed(chat_id)

        reg_token = store.create_oauth_session(chat_id)
        miniapp_url = f"{Config.WEBAPP_BASE_URL}/setup?reg_token={reg_token}"

        report_msg = (
            "🎊 <b>EXPENSUM È PRONTO!</b>\n\n"
            "Ho creato il tuo spazio personale nel database interno PostgreSQL.\n"
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
                        "web_app": {"url": miniapp_url}
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
        if session is not None:
            session.close()


@app.route("/auth/postgres", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def auth_postgres_start():
    """Registrazione su PostgreSQL: raccoglie email e password prima di creare l'utente."""
    reg_token = request.args.get("reg_token") or request.form.get("reg_token")
    if not reg_token:
        return "<h1>Accesso negato</h1><p>Manca il registration token.</p>", 403

    if request.method == "GET":
        return render_template("register_postgres.html", reg_token=reg_token, error=None)

    # POST: valida e crea l'utente
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""

    import re
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template("register_postgres.html", reg_token=reg_token, error="Email non valida.")
    if len(password) < 8:
        return render_template("register_postgres.html", reg_token=reg_token, error="La password deve essere di almeno 8 caratteri.")
    if password != password2:
        return render_template("register_postgres.html", reg_token=reg_token, error="Le password non coincidono.")
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


@app.route("/auth/notion/callback")
def auth_notion_callback():
    """Riceve il codice da Notion, scambia il token e avvia il setup in background."""
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

@app.route("/auth/telegram-login", methods=["GET", "POST"])
def telegram_login_miniapp():
    """Form di login ottimizzato per Telegram WebApp. Aperto tramite /login nel bot."""
    from src.user_store import OAuthSession

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

    # Gestisce accesso da chat_id diverso (cambio account Telegram)
    final_chat_id = chat_id
    if user.chat_id != chat_id:
        try:
            store.reassign_user_chat_id(user.chat_id, chat_id)
        except ValueError:
            return render_template(
                "telegram_login.html",
                state=state,
                error="Questo account Telegram e gia associato a un altro profilo.",
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


# --- SETUP MINI APP (Fase 6) ---

@app.route("/setup")
def setup_form():
    """Mostra il form dinamico per il setup iniziale."""
    reg_token = request.args.get("reg_token")
    if not reg_token:
        return _forbidden_setup_response()
        
    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
             return _forbidden_setup_response()

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return _forbidden_setup_response()

        # --- Branch PostgreSQL: niente schemi Notion, form semplificato ---
        if user.storage_backend == "postgres":
            pg_storage = PostgresStorage(session=s, user_id=user.chat_id)
            existing_accounts = pg_storage.fetch_accounts()
            existing_categories = pg_storage.get_categories()
            existing_subscriptions = pg_storage.fetch_subscriptions()
            is_first_setup = user.setup_completed_at is None
            return render_template(
                "setup_miniapp.html",
                backend="postgres",
                schemas={},
                reg_token=reg_token,
                user_name=user.username or "Utente",
                available_accounts=existing_accounts,
                available_categories=existing_categories,
                available_subscriptions=existing_subscriptions,
                is_first_setup=is_first_setup,
                # I col_* servono solo al ramo Notion: passiamo stringhe vuote come placeholder
                col_accounts_initial_amount="",
                col_accounts_type="",
                col_sub_type="",
                col_sub_amount="",
                col_sub_category="",
                col_sub_account="",
                col_sub_last_billed="",
            )

        # --- Branch Notion (flusso legacy invariato) ---
        if not user.notion_access_token:
            return _forbidden_setup_response()

        # I 3 DB che ci servono per il setup
        setup_db_keys = ["accounts_db_id", "categories_db_id", "subscriptions_db_id"]

        # Fetchiamo SEMPRE gli schemi live da Notion al momento del setup:
        # evita problemi di cache con properties vuote o stantie.
        setup_bindings = {k: getattr(user, k, None) for k in setup_db_keys if getattr(user, k, None)}
        live_schemas_raw = {}
        if setup_bindings:
            try:
                live_schemas_raw = NotionFinanceClient.discover_db_schemas(
                    user.notion_access_token, setup_bindings
                )
                for db_key, schema_data in live_schemas_raw.items():
                    store.save_database_schema(
                        chat_id=user.chat_id,
                        db_key=db_key,
                        notion_db_id=schema_data.get("database_id"),
                        properties_json=json.dumps(schema_data.get("properties", {})),
                        mapped_properties_json=json.dumps(schema_data.get("mapped", {}))
                    )
            except Exception as e:
                logger.exception("[Setup] Errore recupero schemi live da Notion: %s", e)

        # Se il fetch live è fallito, proviamo con la cache
        if not live_schemas_raw:
            stored_schemas = store.get_database_schemas(user.chat_id)
        else:
            stored_schemas = {
                db_key: {
                    "database_id": sd.get("database_id"),
                    "properties": json.dumps(sd.get("properties", {})),
                    "mapped": json.dumps(sd.get("mapped", {}))
                }
                for db_key, sd in live_schemas_raw.items()
            }

        # Prepariamo il dizionario finale con le properties parsate
        schemas = {}
        for db_key in setup_db_keys:
            data = stored_schemas.get(db_key)
            if not data:
                continue
            try:
                props = data["properties"]
                mapped = data.get("mapped")
                schemas[db_key] = {
                    "database_id": data["database_id"],
                    "properties": json.loads(props) if isinstance(props, str) else props,
                    "mapped": json.loads(mapped) if mapped and isinstance(mapped, str) else {}
                }
            except Exception as e:
                logger.exception("[Setup] Errore parsing schema %s: %s", db_key, e)

        # Recupera accounts e categories esistenti su Notion per i dropdown relation
        available_accounts = []
        available_categories = []
        try:
            nc = NotionFinanceClient(
                api_key=user.notion_access_token,
                accounts_db_id=user.accounts_db_id,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_accounts = nc.fetch_accounts()
        except Exception as e:
            logger.exception("[Setup] fetch_accounts fallito: %s", e)
        try:
            nc_cat = NotionFinanceClient(
                api_key=user.notion_access_token,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_categories = nc_cat.fetch_categories()
        except Exception as e:
            logger.exception("[Setup] fetch_categories da Notion fallito: %s", e)
            try:
                from src.storage.models import UserCategory
                # Sessione bindata al tenant per la RLS (user_categories è protetta).
                with store._user_session(user.chat_id) as _cs:
                    cat_rows = _cs.query(UserCategory).filter_by(user_id=user.chat_id).all()
                    available_categories = [
                        {"id": r.notion_page_id or str(r.id), "name": r.name, "monthly_budget": r.monthly_budget}
                        for r in cat_rows
                    ]
            except Exception as e2:
                logger.exception("[Setup] fetch_categories da DB fallito: %s", e2)

        available_subscriptions = []
        try:
            nc_sub = NotionFinanceClient(
                api_key=user.notion_access_token,
                subscriptions_db_id=user.subscriptions_db_id,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_subscriptions = nc_sub.fetch_subscriptions()
        except Exception as e:
            logger.exception("[Setup] fetch_subscriptions da Notion fallito: %s", e)

        return render_template("setup_miniapp.html",
                               backend="notion",
                               schemas=schemas,
                               reg_token=reg_token,
                               user_name=user.username or "Utente",
                               available_accounts=available_accounts,
                               available_categories=available_categories,
                               available_subscriptions=available_subscriptions,
                               is_first_setup=user.setup_completed_at is None,
                               col_accounts_initial_amount=Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT,
                               col_accounts_type=Config.NOTION_ACCOUNTS_COL_TYPE,
                               col_sub_type=Config.NOTION_SUB_COL_TYPE,
                               col_sub_amount=Config.NOTION_SUB_COL_AMOUNT,
                               col_sub_category=Config.NOTION_SUB_COL_CATEGORY,
                               col_sub_account=Config.NOTION_SUB_COL_ACCOUNT,
                               col_sub_last_billed=Config.NOTION_SUB_COL_LAST_BILLED)

@app.route("/api/setup-complete", methods=["POST"])
def api_setup_complete():
    """Riceve i dati dal form Mini App e popola Notion."""
    payload = request.json
    reg_token = payload.get("reg_token")
    items_data = payload.get("items", {}) # { "accounts_db_id": [...], ... }
    
    if not reg_token:
        return jsonify({"error": "Missing token"}), 400
        
    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        # --- Branch PostgreSQL: payload piatto, creazione diretta via PostgresStorage ---
        if user.storage_backend == "postgres":
            pg_storage = PostgresStorage(session=s, user_id=user.chat_id)
            errors: list[str] = []
            fatal_errors: list[str] = []
            created_count = 0

            # 1. Categorie — deduplicazione contro esistenti e contro il payload stesso
            existing_cat_names = {n.lower() for n in pg_storage.get_category_names()}
            seen_cats: set[str] = set()
            for item in items_data.get("categories", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in categories, elemento saltato")
                    continue
                key = name.lower()
                if key in existing_cat_names:
                    errors.append(f"Categoria '{name}' già esistente, saltata")
                    continue
                if key in seen_cats:
                    errors.append(f"Categoria '{name}' duplicata nel payload, saltata")
                    continue
                seen_cats.add(key)
                try:
                    pg_storage.create_category(name)
                    created_count += 1
                except Exception as e:
                    msg = f"Errore categoria '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            # 2. Conti
            for item in items_data.get("accounts", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in accounts, elemento saltato")
                    continue
                try:
                    initial_balance = float(item.get("initial_balance") or 0.0)
                    pg_storage.create_account(name, initial_balance=initial_balance)
                    created_count += 1
                except Exception as e:
                    msg = f"Errore account '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            # 3. Abbonamenti
            for item in items_data.get("subscriptions", []):
                name = (item.get("name") or "").strip()
                if not name:
                    errors.append("Nome vuoto in subscriptions, elemento saltato")
                    continue
                try:
                    pg_storage.create_subscription(
                        name,
                        last_billed=item.get("last_billed") or None,
                    )
                    created_count += 1
                except Exception as e:
                    msg = f"Errore abbonamento '{name}': {e}"
                    errors.append(msg)
                    fatal_errors.append(msg)

            if not fatal_errors:
                if user.setup_completed_at is None:
                    store.mark_setup_completed(user.chat_id)
                    telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
                    try:
                        requests.post(telegram_url, json={
                            "chat_id": user.chat_id,
                            "text": (
                                f"✅ <b>Setup completato!</b>\n"
                                f"Ho creato {created_count} elementi nel database interno.\n\n"
                                f"Ora puoi iniziare a scrivermi le tue spese!"
                            ),
                            "parse_mode": "HTML"
                        }, timeout=TELEGRAM_REQUEST_TIMEOUT)
                    except Exception:
                        pass

                return jsonify({"status": "ok", "created": created_count, "details": errors})

            return jsonify({"error": "Setup failed", "details": errors}), 500

        # --- Branch Notion (flusso legacy invariato) ---
        # Carichiamo gli schemi dal DB così _get_property_name può risolvere
        # i nomi reali delle colonne Notion (es. "Type" invece di "Account type")
        stored_schemas = store.get_database_schemas(user.chat_id)
        db_schemas = {}
        for db_key, data in stored_schemas.items():
            props = data.get("properties")
            mapped = data.get("mapped")
            db_schemas[db_key] = {
                "database_id": data.get("database_id"),
                "properties": json.loads(props) if isinstance(props, str) else (props or {}),
                "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {})
            }

        # DEBUG TEMPORANEO
        for k, v in db_schemas.items():
            logger.debug(
                "[DEBUG] schema %s -> properties keys: %s, mapped: %s",
                k, list(v.get('properties', {}).keys()), v.get('mapped'),
            )

        notion = NotionFinanceClient(
            api_key=user.notion_access_token,
            accounts_db_id=user.accounts_db_id,
            categories_db_id=user.categories_db_id,
            subscriptions_db_id=user.subscriptions_db_id,
            db_schemas=db_schemas,
        )

        errors = []
        created_count = 0

        # --- Helper: estrazione valori dal payload Notion ---

        def _extract_name(prop_data: dict) -> str:
            """Estrae il testo dal primo campo title o rich_text trovato."""
            for _, value in prop_data.items():
                if isinstance(value, dict):
                    for notion_type in ('title', 'rich_text'):
                        if notion_type in value:
                            items_list = value[notion_type]
                            if items_list:
                                return items_list[0].get('text', {}).get('content', '')
            return ''

        def _extract_number(prop_data: dict, prop_name: str):
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'number' in val:
                return val['number']
            return None

        def _extract_select(prop_data: dict, prop_name: str):
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'select' in val:
                return val['select'].get('name')
            return None

        def _extract_relation_ref(prop_data: dict, prop_name: str):
            """Estrae un riferimento relation: può essere un UUID o '__name__:Nome'."""
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and '__relation_ref' in val:
                return val['__relation_ref']
            return None

        def _extract_date(prop_data: dict, prop_name: str) -> str | None:
            """Estrae la data ISO (YYYY-MM-DD) da un campo date Notion."""
            val = prop_data.get(prop_name, {})
            if isinstance(val, dict) and 'date' in val:
                date_obj = val['date']
                if isinstance(date_obj, dict):
                    return date_obj.get('start')
            return None

        def _resolve_ref(ref: str, name_to_id: dict):
            """Risolve un riferimento: se inizia con '__name__:' cerca nella mappa, altrimenti è già un UUID."""
            if not ref:
                return None
            if ref.startswith('__name__:'):
                return name_to_id.get(ref[len('__name__:'):])
            return ref  # già un page_id UUID Notion

        # --- Fase 1: Categorie (devono esistere prima delle subscriptions) ---
        cat_map = {}  # nome → page_id
        seen_cat_names: set[str] = set()
        for prop_data in items_data.get("categories_db_id", []):
            name = ''
            try:
                name = _extract_name(prop_data)
                if not name:
                    errors.append("Nome vuoto in categories_db_id, elemento saltato")
                    continue
                if name.lower() in seen_cat_names:
                    errors.append(f"Categoria '{name}' duplicata nel payload, saltata")
                    continue
                seen_cat_names.add(name.lower())
                result = notion.create_category(name)
                cat_map[name] = result["id"]
                created_count += 1
            except Exception as e:
                errors.append(f"Errore categoria '{name}': {e}")

        # --- Fase 2: Accounts (devono esistere prima delle subscriptions) ---
        acc_map = {}  # nome → page_id
        for prop_data in items_data.get("accounts_db_id", []):
            name = ''
            try:
                logger.debug("[DEBUG] account prop_data keys: %s", list(prop_data.keys()))
                logger.debug("[DEBUG] account prop_data: %s", prop_data)
                name = _extract_name(prop_data)
                acc_type = _extract_select(prop_data, Config.NOTION_ACCOUNTS_COL_TYPE)
                logger.debug(
                    "[DEBUG] account name='%s', type='%s' (cercato con chiave '%s')",
                    name, acc_type, Config.NOTION_ACCOUNTS_COL_TYPE,
                )
                if not name:
                    errors.append("Nome vuoto in accounts_db_id, elemento saltato")
                    continue
                result = notion.create_account(
                    name,
                    initial_amount=_extract_number(prop_data, Config.NOTION_ACCOUNTS_COL_INITIAL_AMOUNT),
                    account_type=_extract_select(prop_data, Config.NOTION_ACCOUNTS_COL_TYPE),
                )
                acc_map[name] = result["id"]
                created_count += 1
            except Exception as e:
                errors.append(f"Errore account '{name}': {e}")

        # --- Fase 3: Subscriptions (risolve relation usando le mappe sopra) ---
        for prop_data in items_data.get("subscriptions_db_id", []):
            name = ''
            try:
                name = _extract_name(prop_data)
                if not name:
                    errors.append("Nome vuoto in subscriptions_db_id, elemento saltato")
                    continue
                notion.create_subscription(
                    name,
                    sub_type=_extract_select(prop_data, Config.NOTION_SUB_COL_TYPE),
                    amount=_extract_number(prop_data, Config.NOTION_SUB_COL_AMOUNT),
                    category_id=_resolve_ref(
                        _extract_relation_ref(prop_data, Config.NOTION_SUB_COL_CATEGORY), cat_map
                    ),
                    account_id=_resolve_ref(
                        _extract_relation_ref(prop_data, Config.NOTION_SUB_COL_ACCOUNT), acc_map
                    ),
                    last_billed=_extract_date(prop_data, Config.NOTION_SUB_COL_LAST_BILLED),
                )
                created_count += 1
            except Exception as e:
                errors.append(f"Errore abbonamento '{name}': {e}")
        
        if created_count > 0 or not errors:
            if user.setup_completed_at is None:
                store.mark_setup_completed(user.chat_id)
                telegram_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
                try:
                    requests.post(telegram_url, json={
                        "chat_id": user.chat_id,
                        "text": (
                            f"✅ <b>Setup completato!</b>\n"
                            f"Ho creato {created_count} elementi nel tuo Notion.\n\n"
                            f"Ora puoi iniziare a scrivermi le tue spese!"
                        ),
                        "parse_mode": "HTML"
                    }, timeout=TELEGRAM_REQUEST_TIMEOUT)
                except Exception:
                    pass

            return jsonify({"status": "ok", "created": created_count, "details": errors})

        return jsonify({"error": "Setup failed", "details": errors}), 500

@app.route("/api/delete-notion-item", methods=["DELETE"])
def api_delete_notion_item():
    """Legacy: archivia un elemento Notion. Mantenuto per backward compat."""
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    page_id = payload.get("page_id")

    if not reg_token or not page_id:
        return jsonify({"error": "Missing reg_token or page_id"}), 400

    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            notion_raw = NotionClient(auth=user.notion_access_token)
            notion_raw.pages.update(page_id=page_id, archived=True)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# CRUD endpoints per la mini app di gestione
# ---------------------------------------------------------------------------

def _resolve_manage_session(reg_token: str):
    """Risolve reg_token → (user, session_db) oppure None."""
    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return None, None, None
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        return user, sess, s


@app.route("/api/manage/add", methods=["POST"])
def api_manage_add():
    """Aggiunge una singola entità (account / category / subscription).

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "data": { "name": "...", "initial_balance": 0.0, "last_billed": "YYYY-MM-DD" }
        }
    """
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    data = payload.get("data") or {}

    if not reg_token or not entity_type:
        return jsonify({"error": "Missing reg_token or entity_type"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    existing = {n.lower() for n in pg.get_category_names()}
                    if name.lower() in existing:
                        return jsonify({"error": f"Categoria '{name}' già esistente"}), 409
                    monthly_budget = float(data["monthly_budget"]) if data.get("monthly_budget") not in (None, "") else None
                    result = pg.create_category(name, monthly_budget=monthly_budget)
                elif entity_type == "account":
                    result = pg.create_account(
                        name,
                        initial_balance=float(data.get("initial_balance") or 0.0),
                        account_type=data.get("account_type") or None,
                    )
                elif entity_type == "subscription":
                    result = pg.create_subscription(
                        name,
                        amount=float(data["amount"]) if data.get("amount") not in (None, "", "0", 0) else None,
                        last_billed=data.get("last_billed") or None,
                        sub_type=data.get("sub_type") or None,
                        account_id=int(data["account_id"]) if data.get("account_id") else None,
                        category_id=int(data["category_id"]) if data.get("category_id") else None,
                    )
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
            else:
                # Notion backend
                stored_schemas = store.get_database_schemas(user.chat_id)
                add_db_schemas: dict = {}
                for db_key, schema_data in stored_schemas.items():
                    _props = schema_data.get("properties")
                    _mapped = schema_data.get("mapped")
                    add_db_schemas[db_key] = {
                        "database_id": schema_data.get("database_id"),
                        "properties": json.loads(_props) if isinstance(_props, str) else (_props or {}),
                        "mapped": json.loads(_mapped) if isinstance(_mapped, str) else (_mapped or {}),
                    }
                notion = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    accounts_db_id=user.accounts_db_id,
                    categories_db_id=user.categories_db_id,
                    subscriptions_db_id=user.subscriptions_db_id,
                    db_schemas=add_db_schemas,
                )
                if entity_type == "category":
                    monthly_budget = float(data["monthly_budget"]) if data.get("monthly_budget") not in (None, "") else None
                    raw = notion.create_category(name, monthly_budget=monthly_budget)
                    result = {"id": raw["id"], "name": name, "monthly_budget": monthly_budget}
                elif entity_type == "account":
                    raw = notion.create_account(
                        name,
                        initial_amount=float(data.get("initial_balance") or 0.0),
                        account_type=data.get("account_type"),
                    )
                    result = {"id": raw["id"], "name": name, "balance": data.get("initial_balance") or 0.0}
                elif entity_type == "subscription":
                    raw = notion.create_subscription(
                        name,
                        sub_type=data.get("sub_type"),
                        amount=float(data["amount"]) if data.get("amount") else None,
                        last_billed=data.get("last_billed") or None,
                        category_id=data.get("category_id") or None,
                        account_id=data.get("account_id") or None,
                    )
                    result = {"id": raw["id"], "name": name, "last_billed": data.get("last_billed")}
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            _trigger_dashboard_refresh(user, s)
            return jsonify({"status": "ok", "entity": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/manage/remove", methods=["DELETE"])
def api_manage_remove():
    """Rimuove una singola entità per entrambi i backend.

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "entity_id": <int per Postgres, page_id UUID per Notion>
        }
    """
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")

    if not reg_token or not entity_type or entity_id is None:
        return jsonify({"error": "Missing reg_token, entity_type o entity_id"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    ok = pg.delete_category(int(entity_id))
                elif entity_type == "account":
                    ok = pg.delete_account(int(entity_id))
                elif entity_type == "subscription":
                    ok = pg.delete_subscription(int(entity_id))
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
                if not ok:
                    return jsonify({"error": "Elemento non trovato"}), 404
            else:
                notion_raw = NotionClient(auth=user.notion_access_token)
                notion_raw.pages.update(page_id=str(entity_id), archived=True)

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            _trigger_dashboard_refresh(user, s)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/manage/update", methods=["PUT"])
def api_manage_update():
    """Modifica un'entità esistente.

    Body JSON:
        {
          "reg_token": "...",
          "entity_type": "account" | "category" | "subscription",
          "entity_id": <int per Postgres, page_id UUID per Notion>,
          "data": { campi da aggiornare }
        }
    """
    payload = request.json or {}
    reg_token = payload.get("reg_token")
    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")
    data = payload.get("data") or {}

    if not reg_token or not entity_type or entity_id is None:
        return jsonify({"error": "Missing reg_token, entity_type o entity_id"}), 400

    from src.user_store import OAuthSession, User
    with store.Session() as s:
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
            return jsonify({"error": "Access denied"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "Access denied"}), 403

        try:
            if user.storage_backend == "postgres":
                pg = PostgresStorage(session=s, user_id=user.chat_id)
                if entity_type == "category":
                    monthly_budget = float(data["monthly_budget"]) if data.get("monthly_budget") not in (None, "") else None
                    result = pg.update_category(
                        int(entity_id),
                        name=data.get("name") or None,
                        monthly_budget=monthly_budget,
                    )
                elif entity_type == "account":
                    result = pg.update_account(
                        int(entity_id),
                        name=data.get("name") or None,
                        balance=float(data["balance"]) if data.get("balance") is not None else None,
                        account_type=data.get("account_type") or None,
                    )
                elif entity_type == "subscription":
                    result = pg.update_subscription(
                        int(entity_id),
                        name=data.get("name") or None,
                        amount=float(data["amount"]) if data.get("amount") not in (None, "", "0", 0) else None,
                        last_billed=data.get("last_billed") or None,
                        sub_type=data.get("sub_type") or None,
                        account_id=int(data["account_id"]) if data.get("account_id") else None,
                        category_id=int(data["category_id"]) if data.get("category_id") else None,
                    )
                else:
                    return jsonify({"error": f"entity_type '{entity_type}' non supportato"}), 400
                if result is None:
                    return jsonify({"error": "Elemento non trovato"}), 404
            else:
                # Notion: risolvi i nomi colonna reali dagli schemi salvati
                stored_schemas = store.get_database_schemas(user.chat_id)
                db_schemas: dict = {}
                for db_key, schema_data in stored_schemas.items():
                    props = schema_data.get("properties")
                    mapped = schema_data.get("mapped")
                    db_schemas[db_key] = {
                        "database_id": schema_data.get("database_id"),
                        "properties": json.loads(props) if isinstance(props, str) else (props or {}),
                        "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {}),
                    }
                notion_client = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    accounts_db_id=user.accounts_db_id,
                    categories_db_id=user.categories_db_id,
                    subscriptions_db_id=user.subscriptions_db_id,
                    db_schemas=db_schemas,
                )

                properties: dict = {}
                if data.get("name"):
                    title_col = notion_client._resolve_title_property_name(
                        entity_type + "s_db_id",
                        getattr(user, entity_type + "s_db_id", None) or "",
                    )
                    properties[title_col] = {"title": [{"text": {"content": data["name"]}}]}
                if data.get("last_billed"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "last_billed", Config.NOTION_SUB_COL_LAST_BILLED
                    )
                    properties[col] = {"date": {"start": data["last_billed"]}}
                if data.get("amount") is not None:
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "sub_amount", Config.NOTION_SUB_COL_AMOUNT
                    )
                    properties[col] = {"number": float(data["amount"])}
                if data.get("account_type"):
                    col = notion_client._get_property_name(
                        "accounts_db_id", "account_type", Config.NOTION_ACCOUNTS_COL_TYPE
                    )
                    properties[col] = {"select": {"name": data["account_type"]}}
                if data.get("monthly_budget") is not None:
                    col = notion_client._get_property_name(
                        "categories_db_id", "monthly_budget", "Monthly Budget"
                    )
                    if col:
                        properties[col] = {"number": float(data["monthly_budget"])}
                if data.get("sub_type"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "sub_type", Config.NOTION_SUB_COL_TYPE
                    )
                    properties[col] = {"select": {"name": data["sub_type"]}}
                if data.get("account_id"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "account", Config.NOTION_SUB_COL_ACCOUNT
                    )
                    properties[col] = {"relation": [{"id": str(data["account_id"])}]}
                if data.get("category_id"):
                    col = notion_client._get_property_name(
                        "subscriptions_db_id", "category", Config.NOTION_SUB_COL_CATEGORY
                    )
                    properties[col] = {"relation": [{"id": str(data["category_id"])}]}
                if properties:
                    try:
                        notion_client._client.pages.update(page_id=str(entity_id), properties=properties)
                    except Exception as notion_err:
                        err_str = str(notion_err)
                        # Se Notion rifiuta una property perché non esiste nel DB, riprova
                        # senza le property opzionali (monthly_budget, account_type, relations)
                        optional_cols = {
                            notion_client._get_property_name("categories_db_id", "monthly_budget", "Monthly Budget"),
                            notion_client._get_property_name("accounts_db_id", "account_type", Config.NOTION_ACCOUNTS_COL_TYPE),
                            notion_client._get_property_name("subscriptions_db_id", "sub_type", Config.NOTION_SUB_COL_TYPE),
                            notion_client._get_property_name("subscriptions_db_id", "account", Config.NOTION_SUB_COL_ACCOUNT),
                            notion_client._get_property_name("subscriptions_db_id", "category", Config.NOTION_SUB_COL_CATEGORY),
                        }
                        optional_cols.discard(None)
                        if "is not a property that exists" in err_str:
                            # Estrai il nome della property incriminata dall'errore Notion
                            bad_prop_match = re.search(r": (.+) is not a property that exists", err_str)
                            if bad_prop_match:
                                bad_prop = bad_prop_match.group(1)
                                logger.warning(
                                    "Notion ha rifiutato property '%s' (schema stale?), retry senza.",
                                    bad_prop,
                                )
                                retry_props = {k: v for k, v in properties.items() if k != bad_prop}
                                if retry_props:
                                    notion_client._client.pages.update(
                                        page_id=str(entity_id), properties=retry_props
                                    )
                                # Invalida il mapping stale dallo schema in memoria
                                for db_key, schema in notion_client._db_schemas.items():
                                    mapped = schema.get("mapped") or {}
                                    stale_keys = [k for k, v in mapped.items() if v == bad_prop]
                                    for k in stale_keys:
                                        del mapped[k]
                                    props = schema.get("properties") or {}
                                    props.pop(bad_prop, None)
                            else:
                                raise
                        else:
                            raise
                result = {"id": entity_id, **data}

            if entity_type == "category":
                _resync_category_cache_from_notion(user)
            _trigger_dashboard_refresh(user, s)
            return jsonify({"status": "ok", "entity": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API CHAT — Telegram-like chat interface for web app
# ---------------------------------------------------------------------------

def _build_financial_storage(user, pg_session=None):
    """Costruisce il FinancialStorage corretto in base al backend dell'utente."""
    if user.storage_backend == "postgres":
        return PostgresStorage(session=pg_session, user_id=user.chat_id)
    # Backend Notion
    stored_schemas = store.get_database_schemas(user.chat_id)
    db_schemas = {}
    for db_key, data in stored_schemas.items():
        props = data.get("properties")
        mapped = data.get("mapped")
        db_schemas[db_key] = {
            "database_id": data.get("database_id"),
            "properties": json.loads(props) if isinstance(props, str) else (props or {}),
            "mapped": json.loads(mapped) if isinstance(mapped, str) else (mapped or {}),
        }
    notion_client = NotionFinanceClient(
        api_key=user.notion_access_token,
        expense_db_id=user.expense_db_id,
        income_db_id=user.income_db_id,
        categories_db_id=user.categories_db_id,
        monthly_balance_db_id=user.monthly_balance_db_id,
        accounts_db_id=user.accounts_db_id,
        subscriptions_db_id=user.subscriptions_db_id,
        pay_transfer_db_id=user.pay_transfer_db_id,
        db_schemas=db_schemas,
    )
    return NotionStorage(notion_client, store=store, user_id=user.chat_id)


def _resolve_account_hint(hint: str | None, accounts: list[dict]) -> dict | None:
    """Risolve un nome conto libero (hint estratto dall'NLP) su un conto reale dell'utente.

    Stessa logica di `_resolve_account_hint` in bot.py: match esatto case-insensitive,
    poi fuzzy match (soglia 0.6) sui nomi conto. None se non menzionato o senza match.
    """
    if not hint:
        return None
    hint_low = hint.strip().lower()
    for acc in accounts:
        if acc["name"].strip().lower() == hint_low:
            return acc
    names_low = [a["name"].strip().lower() for a in accounts]
    matches = difflib.get_close_matches(hint_low, names_low, n=1, cutoff=0.6)
    if matches:
        return next(a for a in accounts if a["name"].strip().lower() == matches[0])
    return None


def _chat_parse_text(
    chat_id: str, text: str, skip_length_check: bool = False, input_method: str = "text",
) -> tuple[list[dict] | None, dict | None, str]:
    """Valida, sanitizza e lancia il parsing LLM (multi-transazione) su un messaggio testuale.

    Ritorna (results, usage, error_reply). Se error_reply è non-None il chiamante
    deve restituire un errore al client senza procedere. `results` è una lista di
    transazioni rilevate (può contenerne più di una, es. scontrino con più voci).
    skip_length_check=True per testo OCR (generato dal sistema, non digitato dall'utente).
    input_method taggato nel ledger token: 'text' (default, chat scritta),
    'voice' (dopo trascrizione) o 'photo' (dopo OCR scontrino) — impostato dal
    chiamante, che sa da quale endpoint (/api/chat/message|voice|photo) proviene.
    """
    from src.expense_parser import ExpenseParser
    from src.rate_limiter import is_rate_limited
    from src.user_store import QuotaExceededError

    # Validazione lunghezza — non applicata a testo OCR (scontrini possono essere lunghi)
    if not skip_length_check and len(text) > Config.MAX_MESSAGE_LEN:
        return None, None, f"⚠️ Messaggio troppo lungo! Massimo {Config.MAX_MESSAGE_LEN} caratteri."

    # Rate limiting
    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return None, None, "⏳ Stai inviando troppi messaggi. Attendi qualche secondo e riprova."

    # Token check
    try:
        plan = store.get_user_plan(chat_id)
        tokens_remaining = plan.get("tokens_remaining", 0)
        TEXT_COST = 800
        if plan.get("plan_type") != "pro" and tokens_remaining < TEXT_COST:
            return None, None, "🔒 Hai esaurito i token mensili. Passa al piano Pro o attendi il rinnovo."
    except Exception:
        pass  # best-effort: non bloccare per errori di quota

    # Sanitizzazione input — difesa da prompt injection
    safe_input = f"[INIZIO INPUT UTENTE]\n{text}\n[FINE INPUT UTENTE]"

    # Carica categorie dal backend corretto
    categories: list[str] = []
    try:
        user = _get_user_by_chat_id(chat_id)
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                categories_raw = storage.get_categories()
                categories = [c["name"] for c in categories_raw if c.get("name")]
        else:
            storage = _build_financial_storage(user)
            categories_raw = storage.get_categories()
            categories = [c["name"] for c in categories_raw if c.get("name")]
    except Exception:
        pass

    # Parsing LLM (multi-transazione: un messaggio può contenere più spese/entrate)
    try:
        parser = ExpenseParser(categories=categories)
        results, usage = parser.parse_multi_with_usage(safe_input)
    except Exception as e:
        logger.exception("Errore ExpenseParser chat: %s", e)
        return None, None, "⚠️ Errore interno durante il parsing. Riprova."

    # Token tracking (best-effort)
    if usage:
        try:
            import uuid
            store.finalize_llm_usage(
                chat_id=chat_id,
                request_key=str(uuid.uuid4()),
                operation="chat_parse",
                provider=usage.get("provider", "unknown"),
                model=usage.get("model", "unknown"),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                input_method=input_method,
            )
        except Exception:
            pass

    return results, usage, ""


def _build_parse_reply(result: dict, from_name: str | None = None, to_name: str | None = None) -> tuple[str, dict]:
    """Costruisce il testo di preview e il dict parsed da mandare al client."""
    parsed_type = result.get("type", "expense")
    amount_str = f"€{result['amount']:.2f}" if result.get("amount") else "importo non specificato"
    date_obj = result.get("date")
    date_str = date_obj.strftime("%d/%m/%Y") if date_obj else "oggi"

    if parsed_type == "expense":
        cat = result.get("category") or "Altro"
        name = result.get("name") or "Spesa"
        reply = f"Ho interpretato **{name}** di {amount_str} nella categoria _{cat}_ ({date_str}). Confermi?"
    elif parsed_type == "transfer":
        name = result.get("name") or "Trasferimento"
        reply = (
            f"📝 Nuovo trasferimento riconosciuto:\n\n"
            f"💰 Importo: **{amount_str}**\n"
            f"🏦 Da: **{from_name or '—'}**\n"
            f"🏦 A: **{to_name or '—'}**\n"
            f"📝 Descrizione: **{name}**\n\nConfermi?"
        )
    else:
        income_type = result.get("income_type") or "Entrata"
        name = result.get("name") or "Entrata"
        reply = f"Ho interpretato **{name}** ({income_type}) di {amount_str} ({date_str}). Confermi?"

    parsed = {
        "type": parsed_type,
        "amount": result.get("amount"),
        "category": result.get("category"),
        "income_type": result.get("income_type"),
        "name": result.get("name"),
        "date": str(result.get("date")),
    }
    return reply, parsed


def _build_transaction_payload(result: dict, accounts: list[dict], categories: list[str]) -> dict:
    """Arricchisce un item parsato con conti/categorie e i flag di step successivo.

    Replica le domande sequenziali del bot Telegram: importo mancante, risoluzione
    conti (con hint LLM) per i trasferimenti, e blocco se mancano conti sufficienti.
    I conti (e per i trasferimenti gli hint risolti) sono sempre inclusi nel `parsed`,
    anche quando manca l'importo, così il frontend non deve rifare un giro di rete
    quando l'utente completa l'importo in un messaggio successivo.
    """
    parsed_type = result.get("type", "expense")
    amount_missing = result.get("amount") is None

    if parsed_type == "transfer":
        from_match = _resolve_account_hint(result.get("from_account"), accounts)
        to_match = _resolve_account_hint(result.get("to_account"), accounts)
        if from_match and to_match and str(from_match["id"]) == str(to_match["id"]):
            to_match = None
        from_name = from_match["name"] if from_match else None
        to_name = to_match["name"] if to_match else None

        reply, parsed = _build_parse_reply(result, from_name=from_name, to_name=to_name)
        parsed["accounts"] = accounts
        parsed["resolved_from_account_id"] = from_match["id"] if from_match else None
        parsed["resolved_from_account_name"] = from_match["name"] if from_match else None
        parsed["resolved_to_account_id"] = to_match["id"] if to_match else None
        parsed["resolved_to_account_name"] = to_match["name"] if to_match else None

        if amount_missing:
            return {
                "type": parsed_type,
                "reply": "📝 Quanto vuoi trasferire? Scrivi solo l'importo (es. 100).",
                "parsed": parsed,
                "needs_amount": True,
                "awaiting_confirm": False,
            }
        if len(accounts) < 2:
            return {
                "type": parsed_type,
                "reply": (
                    "🏦 Ti servono almeno due conti per fare un trasferimento.\n\n"
                    "Aggiungine uno nella tab \"Conti\" del tuo spazio."
                ),
                "parsed": parsed,
                "needs_second_account": True,
                "awaiting_confirm": False,
            }
        # Come bot.py:_advance_transfer_flow — se un conto non è stato risolto dagli hint
        # LLM, si chiede via picker PRIMA di mostrare il riepilogo di conferma.
        if not from_match:
            return {
                "type": parsed_type,
                "reply": "🏦 Da quale conto vuoi spostare i soldi?",
                "parsed": parsed,
                "needs_account_pick": "from",
                "awaiting_confirm": False,
            }
        if not to_match:
            return {
                "type": parsed_type,
                "reply": "🏦 Su quale conto vuoi spostare i soldi?",
                "parsed": parsed,
                "needs_account_pick": "to",
                "awaiting_confirm": False,
            }
        return {"type": parsed_type, "reply": reply, "parsed": parsed, "awaiting_confirm": True}

    reply, parsed = _build_parse_reply(result)
    parsed["accounts"] = accounts
    if parsed_type == "expense":
        parsed["categories"] = categories

    if amount_missing:
        return {
            "type": parsed_type,
            "reply": "📝 Non ho capito l'importo. Prova a ridirmelo, scrivendo solo il numero (es. 20 o 20,50).",
            "parsed": parsed,
            "needs_amount": True,
            "awaiting_confirm": False,
        }
    return {"type": parsed_type, "reply": reply, "parsed": parsed, "awaiting_confirm": True}


def _build_chat_parse_result(chat_id: str, results: list[dict] | None, error_reply: str) -> dict:
    """Costruisce il payload JSON-able per una risposta di parsing chat (0+ transazioni).

    Condiviso da /api/chat/message, /api/chat/voice, /api/chat/photo: tutti e tre
    lanciano lo stesso parsing multi-transazione e devono offrire la stessa UX
    (conti, categorie, trasferimenti) indipendentemente dal canale di input.
    """
    if error_reply:
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=error_reply)
        except Exception:
            pass
        return {"ok": False, "type": "error", "reply": error_reply, "saved": False}

    if not results:
        unknown_reply = "Non ho riconosciuto una transazione nel tuo messaggio. Prova con qualcosa come «ho speso 20€ al supermercato» 🛒"
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=unknown_reply)
        except Exception:
            pass
        return {"ok": True, "type": "unknown", "reply": unknown_reply, "saved": False}

    accounts: list[dict] = []
    categories: list[str] = []
    try:
        user = _get_user_by_chat_id(chat_id)
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                accounts = storage.fetch_accounts()
                categories = storage.get_category_names()
        else:
            storage = _build_financial_storage(user)
            accounts = storage.fetch_accounts()
            categories = storage.get_category_names()
    except Exception as e:
        logger.exception("Errore fetch accounts/categorie chat: %s", e)

    if not accounts:
        no_account_reply = (
            "🏦 Non hai ancora nessun conto su Expensum, quindi non posso registrare la transazione.\n\n"
            "Aggiungine uno nella tab \"Conti\" del tuo spazio, poi rimanda il messaggio."
        )
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=no_account_reply)
        except Exception:
            pass
        return {"ok": False, "type": "no_account", "reply": no_account_reply, "saved": False, "setup_path": "/spazio"}

    transactions = [_build_transaction_payload(r, accounts, categories) for r in results]
    for tx in transactions:
        try:
            store.log_message(chat_id, source="webapp", role="bot", text=tx["reply"], metadata=tx["parsed"])
        except Exception:
            pass

    return {"ok": True, "transactions": transactions}


@app.route("/api/chat/message", methods=["POST"])
def api_chat_message():
    """Parse-only: interpreta il messaggio via LLM (anche multi-transazione), non salva."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Testo vuoto"}), 400

    results, _usage, error_reply = _chat_parse_text(chat_id, text)

    try:
        store.log_message(chat_id, source="webapp", role="user", text=text)
    except Exception:
        pass

    return jsonify(_build_chat_parse_result(chat_id, results, error_reply))


@app.route("/api/chat/confirm", methods=["POST"])
def api_chat_confirm():
    """Salva la transazione parsata dopo conferma esplicita dell'utente.

    Il conto (o i due conti, per un trasferimento) va scelto esplicitamente dal
    frontend — niente più default silenzioso sul primo conto dell'utente, per
    parità con il bot Telegram (bot.py:2472-2515, 2517-2549).
    """
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    parsed = data.get("parsed") or {}
    parsed_type = parsed.get("type", "expense")
    category_override = data.get("category")
    account_id = data.get("account_id")
    from_account_id = data.get("from_account_id")
    to_account_id = data.get("to_account_id")

    if not parsed.get("amount"):
        return jsonify({"error": "Dati transazione mancanti"}), 400

    if parsed_type == "transfer":
        if not from_account_id or not to_account_id:
            return jsonify({"error": "Conto di origine/destinazione mancante"}), 400
        if str(from_account_id) == str(to_account_id):
            return jsonify({"error": "Il conto di destinazione deve essere diverso da quello di origine"}), 400
    elif not account_id:
        return jsonify({"error": "Conto mancante"}), 400

    user = _get_user_by_chat_id(chat_id)
    if not user:
        return jsonify({"error": "Utente non trovato"}), 404

    # Converti la data da stringa a oggetto date (il parser la serializza come str)
    from datetime import date as _date
    raw_date = parsed.get("date")
    try:
        tx_date = datetime.strptime(str(raw_date).split("T")[0], "%Y-%m-%d").date()
    except (ValueError, AttributeError, TypeError):
        tx_date = _date.today()

    # Controlla se è la prima spesa (per first_expense_tracked) prima di salvare
    _is_first_expense = False
    try:
        if user.storage_backend == "postgres" and parsed_type == "expense":
            # Sessione bindata al tenant per la RLS (expenses è protetta).
            with store._user_session(chat_id) as _s:
                from src.storage.models import Expense as _ExpenseModel
                _count = _s.query(_ExpenseModel).filter_by(user_id=chat_id).count()
                _is_first_expense = _count == 0
    except Exception:
        pass

    def _save(storage) -> None:
        if parsed_type == "expense":
            storage.create_expense(
                expense_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                category_name=category_override or parsed.get("category") or "Altro",
                name=parsed.get("name") or "Spesa",
                account_id=account_id,
            )
        elif parsed_type == "transfer":
            storage.create_transfer(
                transfer_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                name=parsed.get("name") or "Trasferimento",
            )
        else:
            storage.create_income(
                income_date=tx_date,
                amount=float(parsed.get("amount") or 0),
                income_type=parsed.get("income_type") or "Stipendio",
                name=parsed.get("name") or "Entrata",
                account_id=account_id,
            )

    saved = False
    try:
        if user.storage_backend == "postgres":
            with store.Session() as s:
                storage = _build_financial_storage(user, pg_session=s)
                _save(storage)
        else:
            storage = _build_financial_storage(user)
            _save(storage)
        saved = True
    except Exception as e:
        logger.exception("Errore salvataggio transazione confermata: %s", e)

    if saved:
        input_method = data.get("input_method", "text")
        analytics.track(chat_id, "expense_tracked", {
            "input_method": input_method,
            "storage_backend": user.storage_backend,
            "transaction_type": parsed_type,
        })
        store.record_tx_event(chat_id, parsed_type, input_method, "confirmed", "webapp")
        if _is_first_expense:
            analytics.track(chat_id, "first_expense_tracked", {"input_method": input_method})
    else:
        analytics.track(chat_id, "expense_tracking_failed", {"reason": "save_error"})
        store.record_tx_event(
            chat_id, parsed_type, data.get("input_method", "text"), "failed", "webapp",
            reason="save_error",
        )

    amount_str = f"€{float(parsed.get('amount', 0)):.2f}"
    if parsed_type == "expense":
        cat = category_override or parsed.get("category") or "Altro"
        name = parsed.get("name") or "Spesa"
        if saved:
            reply = f"✅ Ho registrato **{name}** di {amount_str} nella categoria _{cat}_."
        else:
            reply = f"⚠️ Ho interpretato **{name}** di {amount_str}, ma non sono riuscito a salvarlo. Riprova."
    elif parsed_type == "transfer":
        from_name = parsed.get("resolved_from_account_name") or "—"
        to_name = parsed.get("resolved_to_account_name") or "—"
        if saved:
            reply = f"✅ Trasferiti {amount_str} da **{from_name}** a **{to_name}**."
        else:
            reply = f"⚠️ Ho interpretato il trasferimento di {amount_str}, ma non sono riuscito a salvarlo. Riprova."
    else:
        income_type = parsed.get("income_type") or "Entrata"
        name = parsed.get("name") or "Entrata"
        if saved:
            reply = f"✅ Ho registrato **{name}** ({income_type}) di {amount_str}."
        else:
            reply = f"⚠️ Ho interpretato **{name}** di {amount_str}, ma non sono riuscito a salvarlo. Riprova."

    # Log risposta finale bot
    try:
        store.log_message(chat_id, source="webapp", role="bot", text=reply, metadata=parsed if saved else None)
    except Exception:
        pass

    return jsonify({"ok": saved, "saved": saved, "reply": reply, "is_first_expense": _is_first_expense and saved})


@app.route("/api/chat/voice", methods=["POST"])
def api_chat_voice():
    """Trascrive un messaggio vocale via Gemini e lo processa come testo."""
    import tempfile
    from src.rate_limiter import is_rate_limited

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return jsonify({"ok": False, "reply": "⏳ Troppi messaggi. Attendi qualche secondo.", "saved": False})

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "File audio mancante"}), 400

    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return jsonify({
            "ok": False,
            "reply": f"⚠️ Audio troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
            "saved": False,
        }), 413

    # Trascrizione Gemini Vertex AI
    transcribed = ""
    try:
        from google.genai import types as genai_types

        from src.vertex_ai_client import get_vertex_ai_client

        audio_bytes = audio_file.read()
        if len(audio_bytes) > max_bytes:
            return jsonify({
                "ok": False,
                "reply": f"⚠️ Audio troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
                "saved": False,
            }), 413
        if len(audio_bytes) < 100:
            return jsonify({"ok": False, "reply": "⚠️ Audio troppo corto o vuoto.", "saved": False})

        client_ai = get_vertex_ai_client()
        audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type="audio/webm")
        response = client_ai.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[
                "Trascrivi esattamente e parola per parola questo audio in italiano. "
                "Restituisci SOLO ed esclusivamente il testo trascritto, nient'altro.",
                audio_part,
            ],
        )
        transcribed = (response.text or "").strip()
    except Exception as e:
        logger.exception("Errore trascrizione voce chat: %s", e)
        return jsonify({"ok": False, "reply": "⚠️ Errore durante la trascrizione audio. Riprova o scrivi il messaggio.", "saved": False})

    if not transcribed:
        return jsonify({"ok": False, "reply": "⚠️ Non sono riuscito a trascrivere l'audio. Parla più chiaramente o scrivi il messaggio.", "saved": False})

    results, _usage, error_reply = _chat_parse_text(chat_id, transcribed, input_method="voice")

    user_text = f"🎤 {transcribed}"
    try:
        store.log_message(chat_id, source="webapp", role="user", text=user_text)
    except Exception:
        pass

    payload = _build_chat_parse_result(chat_id, results, error_reply)
    payload["transcription"] = transcribed
    return jsonify(payload)


@app.route("/api/chat/photo", methods=["POST"])
def api_chat_photo():
    """Analizza un'immagine di scontrino via OCR e la processa come testo."""
    import tempfile
    from src.rate_limiter import is_rate_limited

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if is_rate_limited(chat_id, max_messages=Config.MAX_MESSAGES_PER_MINUTE):
        return jsonify({"ok": False, "reply": "⏳ Troppi messaggi. Attendi qualche secondo.", "saved": False})

    image_file = request.files.get("image")
    if not image_file:
        return jsonify({"error": "Immagine mancante"}), 400

    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return jsonify({
            "ok": False,
            "reply": f"⚠️ Immagine troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
            "saved": False,
        }), 413

    ocr_text = ""
    try:
        from src.ocr_client import OcrClient, OCRError

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_file.save(tmp.name)
            tmp_path = tmp.name

        if os.path.getsize(tmp_path) > max_bytes:
            os.unlink(tmp_path)
            return jsonify({
                "ok": False,
                "reply": f"⚠️ Immagine troppo grande! Limite: {Config.MAX_FILE_SIZE_MB}MB.",
                "saved": False,
            }), 413

        try:
            ocr_text = OcrClient().extract_text_from_image(tmp_path)
        except OCRError:
            return jsonify({"ok": False, "reply": "⚠️ Non riesco a leggere lo scontrino. Riprova con una foto più nitida e ben illuminata.", "saved": False})
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.exception("Errore OCR chat: %s", e)
        return jsonify({"ok": False, "reply": "⚠️ Errore durante l'analisi dell'immagine. Riprova.", "saved": False})

    # 🛡️ Sanitizzazione testo OCR — rimuove Unicode pericolosi e rileva injection
    from src.input_sanitizer import sanitize_ocr_text, InjectionDetectedError
    try:
        ocr_text = sanitize_ocr_text(ocr_text, chat_id)
    except InjectionDetectedError:
        store.logout_user(chat_id)
        return jsonify({
            "ok": False,
            "reply": (
                f"🚫 Comportamento malevolo rilevato. "
                f"Il tuo account è stato disabilitato. "
                f"Per chiarimenti scrivi a: {Config.SUPPORT_EMAIL}"
            ),
            "saved": False,
            "banned": True,
        })

    results, _usage, error_reply = _chat_parse_text(chat_id, ocr_text, skip_length_check=True, input_method="photo")

    user_text = f"📷 {ocr_text[:200]}"
    try:
        store.log_message(chat_id, source="webapp", role="user", text=user_text)
    except Exception:
        pass

    payload = _build_chat_parse_result(chat_id, results, error_reply)
    if payload.get("type") == "unknown":
        payload["reply"] = "⚠️ Ho letto il testo dello scontrino ma non ho riconosciuto una transazione. Prova a scrivere la spesa manualmente."
    return jsonify(payload)


@app.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    """Ritorna la cronologia condivisa: messaggi da Telegram e web app + report."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    limit = min(int(request.args.get("limit", 60)), 100)

    try:
        messages = store.get_chat_history(chat_id, limit=limit)

        # Arricchisce con i report salvati (appaiono inline come messaggi bot), evitando
        # doppioni per i report che hanno già un messaggio esplicito di notifica in chat
        # (weekly/monthly plan loggano un saluto con lo stesso share_token in metadata).
        try:
            already_notified_tokens = {
                m.get("metadata", {}).get("share_token")
                for m in messages
                if m.get("metadata", {}).get("share_token")
            }
            user = _get_user_by_chat_id(chat_id)
            if user:
                if user.storage_backend == "postgres":
                    with store.Session() as s:
                        pg = PostgresStorage(session=s, user_id=chat_id)
                        reports = pg.get_reports_for_user(chat_id, limit=10)
                else:
                    storage = _build_financial_storage(user)
                    reports = storage.get_reports_for_user(chat_id, limit=10)

                for r in reports:
                    if r.get("share_token") in already_notified_tokens:
                        continue
                    messages.append({
                        "id": f"report-{r.get('share_token', '')}",
                        "source": "telegram",
                        "role": "bot",
                        "text": (r.get("text_content") or "")[:500] + ("…" if len(r.get("text_content") or "") > 500 else ""),
                        "created_at": str(r.get("report_date") or r.get("created_at") or ""),
                        "metadata": {
                            "report_type": r.get("report_type"),
                            "share_token": r.get("share_token"),
                        },
                    })

                messages.sort(key=lambda m: m.get("created_at") or "", reverse=False)
                messages = messages[-limit:]
        except Exception:
            pass  # i report sono opzionali

        return jsonify({"messages": messages, "count": len(messages)})
    except Exception as e:
        logger.exception("Errore api_chat_history: %s", e)
        return jsonify({"messages": [], "count": 0})


# ---------------------------------------------------------------------------
# API ANALYTICS — Telegram Mini App
# ---------------------------------------------------------------------------
import hmac
import hashlib
from functools import wraps
from collections import defaultdict
from calendar import month_abbr


def _validate_telegram_init_data(init_data_raw: str) -> dict | None:
    """Valida HMAC-SHA256 di Telegram WebApp initData e ritorna i campi parsati.

    Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    token = Config.TELEGRAM_BOT_TOKEN.encode()
    secret_key = hmac.new(b"WebAppData", token, hashlib.sha256).digest()

    from urllib.parse import unquote
    params: dict[str, str] = {}
    received_hash: str | None = None
    for part in init_data_raw.split("&"):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        if k == "hash":
            received_hash = v
        else:
            params[k] = unquote(v)  # signature inclusa nel dcs (Bot API 7.0+)

    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_json = params.get("user", "{}")
    try:
        import json as _json
        from urllib.parse import unquote
        user_data = _json.loads(unquote(user_json))
    except Exception:
        user_data = {}

    return {"user": user_data, "chat_id": str(user_data.get("id", ""))}


def _tg_webapp_auth(f):
    """Decorator: autentica via Telegram WebApp o sessione browser."""
    from flask import g
    @wraps(f)
    def decorated(*args, **kwargs):
        chat_id, auth_mode = _resolve_request_chat_id()
        if not chat_id:
            return jsonify({"error": "Unauthorized"}), 401
        g.chat_id = chat_id
        g.auth_mode = auth_mode
        return f(*args, **kwargs)
    return decorated


@app.route("/api/auth/session", methods=["GET"])
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
        "redirect_to": None if redirect_to == "/chat" else redirect_to,
    })


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Dati account e piano per la pagina Impostazioni."""
    from src.user_store import User
    chat_id, auth_mode = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        telegram_connected = not str(chat_id).startswith("web_")
        name_parts = (user.username or "").strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else None
        last_name = name_parts[1] if len(name_parts) > 1 else None

    plan = store.get_user_plan(chat_id)
    reset_at = plan.get("tokens_reset_at")
    tokens_usage_percent = 0
    tokens_total = plan.get("tokens_total", 1)
    if tokens_total:
        used = plan.get("tokens_used_current_cycle", 0) + plan.get("tokens_reserved_current_cycle", 0)
        tokens_usage_percent = round(used / tokens_total * 100, 1)

    return jsonify({
        "chat_id": chat_id,
        "auth_mode": auth_mode,
        "account": {
            "email": user.email if hasattr(user, "email") else None,
            "first_name": first_name,
            "last_name": last_name,
            "telegram_connected": telegram_connected,
            "telegram_chat_id": chat_id if telegram_connected else None,
            "storage_backend": user.storage_backend,
            "is_active": user.is_active,
            "privacy_policy_version_accepted": user.privacy_policy_version_accepted,
            "privacy_policy_current_version": Config.CURRENT_PRIVACY_POLICY_VERSION,
        },
        "plan": {
            "plan_type": plan.get("plan_type", "free"),
            "tokens_total": tokens_total,
            "tokens_used_current_cycle": plan.get("tokens_used_current_cycle", 0),
            "tokens_reserved_current_cycle": plan.get("tokens_reserved_current_cycle", 0),
            "tokens_remaining": plan.get("tokens_remaining", 0),
            "tokens_usage_percent": tokens_usage_percent,
            "tokens_reset_at": reset_at.isoformat() if reset_at else None,
            "alert": plan.get("alert"),
        },
    })


@app.route("/api/telegram/link", methods=["POST"])
def api_telegram_link():
    """Genera un deep link per collegare l'account web corrente a Telegram."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    if not str(chat_id).startswith("web_"):
        return jsonify({"already_linked": True})

    if not Config.TELEGRAM_BOT_USERNAME:
        return jsonify({"error": "Telegram bot non configurato"}), 500

    state = store.create_oauth_session(chat_id)
    link = f"https://t.me/{Config.TELEGRAM_BOT_USERNAME}?start=link_{state}"
    return jsonify({"already_linked": False, "link": link})


@app.route("/api/settings/logout", methods=["POST"])
def api_settings_logout():
    """Sospende l'account (is_active=False) e invalida la sessione corrente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    store.logout_user(chat_id)
    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


@app.route("/api/settings/change-email", methods=["POST"])
@limiter.limit("5 per minute")
def api_settings_change_email():
    """Cambia l'email dell'account. Richiede la password corrente per re-autenticazione."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    new_email = (body.get("new_email") or "").strip().lower()
    current_password = body.get("current_password") or ""

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        return jsonify({"error": "Email non valida."}), 400

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        old_email = user.email

    if not old_email or not store.verify_password(old_email, current_password):
        return jsonify({"error": "Password corrente errata."}), 401

    if store.get_user_by_email_any_status(new_email):
        return jsonify({"error": "Email già in uso."}), 409

    store.update_email(chat_id, new_email)
    store.write_audit_log(
        chat_id, actor="user", action="change_email",
        metadata={"old_email": old_email, "new_email": new_email},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@app.route("/api/settings/change-password", methods=["POST"])
@limiter.limit("5 per minute")
def api_settings_change_password():
    """Cambia la password dell'account. Richiede la password corrente per re-autenticazione."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify({"error": "La nuova password deve essere di almeno 8 caratteri."}), 400

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        email = user.email

    if not email or not store.verify_password(email, current_password):
        return jsonify({"error": "Password corrente errata."}), 401

    # update_password incrementa token_version: tutte le sessioni esistenti
    # (compresa questa) vengono invalidate. Riallineo la sessione del device
    # corrente al nuovo valore così chi cambia password non viene sloggato,
    # mentre gli altri dispositivi sì.
    store.update_password(chat_id, new_password)
    if session.get("user_logged_in"):
        session["token_version"] = store.get_token_version(chat_id)
    store.write_audit_log(
        chat_id, actor="user", action="change_password",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True})


@app.route("/api/settings/logout-all-devices", methods=["POST"])
def api_settings_logout_all_devices():
    """Revoca tutte le sessioni dell'utente su ogni dispositivo, inclusa questa.

    Incrementa `token_version`: ogni cookie di sessione emesso in precedenza
    diventa invalido al confronto in `_get_session_chat_id`. A differenza di
    /api/settings/logout NON sospende l'account (is_active resta True).
    """
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    store.bump_token_version(chat_id)
    store.write_audit_log(
        chat_id, actor="user", action="logout_all_devices",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


@app.route("/api/settings/delete-account", methods=["POST"])
@app.route("/api/privacy/delete-account", methods=["POST"])
def api_settings_delete_account():
    """Elimina definitivamente account e dati locali. Richiede confirm='DELETE'.

    Esposto anche sotto /api/privacy/delete-account (Art. 17 GDPR) per coerenza
    col namespace degli altri endpoint diritti interessato.
    """
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    if (body.get("confirm") or "").strip().upper() != "DELETE":
        return jsonify({"error": "Conferma non valida. Scrivi DELETE per procedere."}), 400

    # Audit log PRIMA della cancellazione: dopo, la riga users non esiste più.
    store.write_audit_log(
        chat_id, actor="user", action="delete_account",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )

    result = store.delete_user_completely(chat_id)
    if result == "not_found":
        return jsonify({"error": "Utente non trovato."}), 404

    session.clear()
    return jsonify({"ok": True, "redirect_url": "/login"})


# ---------------------------------------------------------------------------
# Privacy API — diritti dell'interessato (GDPR Art. 15, 17, 20)
# ---------------------------------------------------------------------------

@app.route("/api/privacy/accept-policy", methods=["POST"])
def api_privacy_accept_policy():
    """Art. 7 GDPR — registra l'accettazione esplicita della versione corrente della privacy policy."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    version = Config.CURRENT_PRIVACY_POLICY_VERSION
    store.accept_privacy_policy(chat_id, version)
    store.write_audit_log(
        chat_id, actor="user", action="consent_change",
        metadata={"consent_type": "privacy_policy", "version": version},
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"ok": True, "privacy_policy_version_accepted": version})


@app.route("/api/privacy/export-json", methods=["GET"])
@limiter.limit("5 per minute")
def api_privacy_export_json():
    """Art. 15 GDPR — copia completa dei dati personali dell'utente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        export_data = build_export_json(s, user)

    store.write_audit_log(
        chat_id, actor="user", action="export_json",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )
    return jsonify(export_data)


@app.route("/api/privacy/export-csv", methods=["GET"])
@limiter.limit("5 per minute")
def api_privacy_export_csv():
    """Art. 20 GDPR — transazioni dell'utente in formato CSV portabile."""
    import csv
    import io
    from datetime import date

    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401

    with store.Session() as s:
        user = s.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        rows = build_csv_rows(s, user)

    if rows is None:
        return jsonify({"error": NOTION_CSV_UNAVAILABLE_MESSAGE}), 404

    store.write_audit_log(
        chat_id, actor="user", action="export_csv",
        ip_address=request.remote_addr, user_agent=request.headers.get("User-Agent"),
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(row)

    filename = f"expensum_export_{date.today().isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Onboarding API
# ---------------------------------------------------------------------------

@app.route("/api/onboarding/status", methods=["GET"])
def api_onboarding_status():
    """Stato corrente del wizard di onboarding."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"authorized": False}), 401
    prefs = store.get_user_preferences(chat_id)
    return jsonify(prefs)


@app.route("/api/onboarding/step", methods=["POST"])
def api_onboarding_step():
    """Salva i dati di uno step del wizard."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    step = body.get("step")
    data = body.get("data", {})
    if not step:
        return jsonify({"error": "step required"}), 400
    store.save_onboarding_progress(chat_id, step, data)
    return jsonify({"status": "ok"})


@app.route("/api/onboarding/generate-categories", methods=["POST"])
def api_onboarding_generate_categories():
    """Genera categorie personalizzate con Mistral Small in base al lifestyle."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    lifestyle = body.get("lifestyle", {})
    try:
        from src.mistral_client import MistralClient
        client = MistralClient()
        categories = client.generate_lifestyle_categories(lifestyle)
    except Exception as e:
        logger.warning("Errore generazione categorie onboarding: %s", e)
        from src.workspace_bootstrapper import DEFAULT_CATEGORIES
        categories = list(DEFAULT_CATEGORIES)
    return jsonify({"categories": categories})


@app.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    """Finalizza l'onboarding: genera categorie da hobby e segna come completato.

    Body: { "hobbies": ["palestra", "streaming", ...] }
    Le categorie vengono generate via lookup table statica (categories_from_hobbies)
    senza chiamate AI — l'AI per categorie viene usata in futuro su dati reali.
    """
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    hobbies: list[str] = body.get("hobbies", [])

    user = _get_user_by_chat_id(chat_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    from src.workspace_bootstrapper import categories_from_hobbies
    categories = categories_from_hobbies(hobbies)

    try:
        if user.storage_backend == "postgres":
            db_session = store.Session()
            storage = PostgresStorage(session=db_session, user_id=chat_id)
            created = bootstrap_lifestyle_categories(storage, categories)
            db_session.commit()
        else:
            from src.notion_client import NotionFinanceClient
            from src.storage.notion_storage import NotionStorage
            notion_client = NotionFinanceClient(
                api_key=user.notion_access_token,
                categories_db_id=user.categories_db_id,
            )
            storage = NotionStorage(notion_client)
            created = bootstrap_lifestyle_categories(storage, categories)
    except Exception as e:
        logger.error("Errore bootstrap lifestyle categories: %s", e)
        created = []

    store.complete_onboarding(chat_id)
    analytics.track(chat_id, "onboarding_completed", {"platform": "web", "hobbies": hobbies})
    return jsonify({"status": "ok", "categories_created": created})


@app.route("/api/onboarding/age-confirm", methods=["POST"])
def api_onboarding_age_confirm():
    """Registra l'attestazione età 18+ dell'utente (D.Lgs. 101/2018)."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    if not body.get("confirmed", False):
        return jsonify({"error": "Age not confirmed"}), 403
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    store.set_age_attestation(chat_id, ip_address=ip, platform="web")
    return jsonify({"status": "ok"})


@app.route("/api/demo/load", methods=["POST"])
def api_demo_load():
    """Carica 30 giorni di spese demo (prefissate [Demo]) per l'utente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from src.demo_data import load_demo_data
        storage = _get_storage(chat_id)
        count = load_demo_data(storage)
        store.set_has_demo_data(chat_id, True)
        return jsonify({"ok": True, "expense_count": count})
    except Exception as e:
        app.logger.warning("[User %s] Errore caricamento demo data: %s", chat_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    """Cancella le spese demo (prefissate [Demo]) e resetta il flag has_demo_data."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        storage = _get_storage(chat_id)
        count = store.clear_demo_data(chat_id, storage)
        return jsonify({"ok": True, "deleted": count})
    except Exception as e:
        app.logger.warning("[User %s] Errore pulizia demo data: %s", chat_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/user/preferences", methods=["GET"])
def api_user_preferences_get():
    """Restituisce le preferenze utente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(store.get_user_preferences(chat_id))


@app.route("/api/user/preferences", methods=["PUT"])
def api_user_preferences_put():
    """Aggiorna le preferenze utente."""
    chat_id, _ = _resolve_request_chat_id()
    if not chat_id:
        return jsonify({"error": "Unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    step = body.pop("step", "preferences_update")
    store.save_onboarding_progress(chat_id, step, body)
    return jsonify({"status": "ok"})


def _month_label(year: int, month: int) -> str:
    return f"{month_abbr[month]} {str(year)[-2:]}"


def _start_date_for_months(months: int):
    from datetime import date
    today = date.today()
    # Torna al primo giorno del mese, months-1 mesi indietro,
    # così da includere esattamente `months` mesi (incluso il corrente).
    offset = months - 1
    m = today.month - offset
    y = today.year + m // 12
    m = m % 12
    if m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _get_user_plan_type(chat_id: str) -> str:
    """Ritorna 'free' o 'pro' per l'utente corrente."""
    try:
        plan = store.get_user_plan(chat_id)
        return plan.get("plan_type", "free")
    except Exception:
        return "free"


def _is_pro(chat_id: str) -> bool:
    """True se l'utente è Pro."""
    return _get_user_plan_type(chat_id) == "pro"


@app.route("/api/analytics/overview")
@_tg_webapp_auth
def analytics_overview():
    """Ritorna risparmio mensile e spesa mensile per account negli ultimi N mesi."""
    from flask import g
    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)

        transactions = storage.fetch_all_transactions(start, end)
        incomes = storage.fetch_income(start, end)
        accounts = storage.fetch_accounts()

    account_map = {a["id"]: a["name"] for a in accounts}

    # Aggrega spese per (anno, mese)
    monthly_expenses: dict[tuple, float] = defaultdict(float)
    monthly_by_account: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for t in transactions:
        d = t["date"]
        key = (d.year, d.month)
        monthly_expenses[key] += t["amount"]
        acc_name = account_map.get(t["account_id"], "Altro")
        monthly_by_account[key][acc_name] += t["amount"]

    monthly_income: dict[tuple, float] = defaultdict(float)
    for inc in incomes:
        d = inc["date"]
        key = (d.year, d.month)
        monthly_income[key] += inc["amount"]

    # Costruisce lista mesi ordinata
    all_keys = sorted(set(monthly_expenses) | set(monthly_income))
    savings = []
    for key in all_keys:
        y, m = key
        inc_total = round(monthly_income.get(key, 0.0), 2)
        exp_total = round(monthly_expenses.get(key, 0.0), 2)
        savings.append({
            "month": _month_label(y, m),
            "income": inc_total,
            "expenses": exp_total,
            "net": round(inc_total - exp_total, 2),
        })

    totals_by_account = []
    for key in all_keys:
        y, m = key
        for acc_name, amount in monthly_by_account[key].items():
            totals_by_account.append({
                "month": _month_label(y, m),
                "account": acc_name,
                "amount": round(amount, 2),
            })

    return jsonify({"savings": savings, "totals_by_account": totals_by_account, "plan_type": plan_type})


@app.route("/api/analytics/categories-expense")
@_tg_webapp_auth
def analytics_categories_expense():
    """Ritorna spese per categoria: storico mensile e medie per ultimi N mesi.
    
    Query params:
        months=N        (default 6, max 24 Pro / 6 Free)
        category=NAME   (filtra per categoria, solo Pro)
        granularity=    "monthly" (default) | "weekly" (solo Pro)
    """
    from flask import g
    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    # Filtro categoria (solo Pro puo' filtrare)
    category_filter = request.args.get("category", "").strip() if plan_type == "pro" else ""
    granularity = request.args.get("granularity", "monthly") if plan_type == "pro" else "monthly"

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)
        categories = storage.get_categories()

    budget_map = {c["name"]: c.get("monthly_budget") for c in categories}

    if category_filter:
        transactions = [t for t in transactions if (t.get("category") or "Altro").lower() == category_filter.lower()]

    # Aggrega per (anno, mese, categoria) o (anno, week, categoria)
    monthly_cat: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        d = t["date"]
        if granularity == "weekly":
            iso = d.isocalendar()
            key = (iso[0], iso[1])
        else:
            key = (d.year, d.month)
        cat = t.get("category") or "Altro"
        monthly_cat[key][cat] += t["amount"]

    all_keys = sorted(monthly_cat.keys())

    by_category = []
    for key in all_keys:
        if granularity == "weekly":
            y, w = key
            label = f"W{w} {str(y)[-2:]}"
        else:
            y, m = key
            label = _month_label(y, m)
        for cat, amount in monthly_cat[key].items():
            by_category.append({
                "month": label,
                "name": cat,
                "amount": round(amount, 2),
                "budget": budget_map.get(cat),
            })

    # Media per categoria su tutto il periodo
    cat_totals: dict[str, list[float]] = defaultdict(list)
    for key, cats in monthly_cat.items():
        for cat, amount in cats.items():
            cat_totals[cat].append(amount)

    averages = [
        {"name": cat, "avg": round(sum(vals) / len(vals), 2)}
        for cat, vals in cat_totals.items()
    ]
    averages.sort(key=lambda x: x["avg"], reverse=True)

    return jsonify({"by_category": by_category, "averages": averages, "plan_type": plan_type})


@app.route("/api/analytics/income")
@_tg_webapp_auth
def analytics_income():
    """Ritorna storico entrate mensili negli ultimi N mesi."""
    from flask import g
    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        incomes = storage.fetch_income(start, end)

    monthly: dict[tuple, float] = defaultdict(float)
    for inc in incomes:
        d = inc["date"]
        key = (d.year, d.month)
        monthly[key] += inc["amount"]

    result = [
        {"month": _month_label(y, m), "total": round(amount, 2)}
        for (y, m), amount in sorted(monthly.items())
    ]
    return jsonify({"monthly": result, "plan_type": plan_type})


@app.route("/api/analytics/wealth")
@_tg_webapp_auth
def analytics_wealth():
    """Ritorna saldo corrente per account (capitale totale)."""
    from flask import g
    plan_type = _get_user_plan_type(g.chat_id)
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        accounts = storage.fetch_accounts()

    result = [
        {"name": a["name"], "balance": round(a["current_balance"] or 0.0, 2)}
        for a in accounts
        if a.get("current_balance") is not None
    ]
    return jsonify({"accounts": result, "plan_type": plan_type})


# ---------------------------------------------------------------------------
# NUOVI ENDPOINT ANALYTICS (Fase 2)
# ---------------------------------------------------------------------------

@app.route("/api/analytics/capital-trend")
@_tg_webapp_auth
def analytics_capital_trend():
    """Ritorna lo storico del capitale (somma saldi conti) mese per mese.
    
    Calcola per ogni mese il saldo aggregato di tutti i conti:
    opening_balance + sum(income fino a quel mese) - sum(expenses fino a quel mese).
    """
    from flask import g
    from datetime import date
    end = date.today()

    plan_type = _get_user_plan_type(g.chat_id)
    max_months = 24 if plan_type == "pro" else 6
    months = min(int(request.args.get("months", 6)), max_months)
    view_start = _start_date_for_months(months)

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        accounts = storage.fetch_accounts()
        # Fetch ALL data to calculate running balance correctly
        transactions = storage.fetch_all_transactions(date(2000, 1, 1), end)
        incomes = storage.fetch_income(date(2000, 1, 1), end)

    # Mappe di utilità
    acc_id_to_name = {a["id"]: a["name"] for a in accounts}
    acc_id_to_opening = {a["id"]: (a.get("opening_balance", 0.0) or 0.0) for a in accounts}
    
    # Aggrega entrate e uscite per (anno, mese) e per ID conto
    # Usiamo None come chiave per le transazioni senza conto ("Altro")
    monthly_income: dict[tuple, dict[int | None, float]] = defaultdict(lambda: defaultdict(float))
    monthly_expense: dict[tuple, dict[int | None, float]] = defaultdict(lambda: defaultdict(float))

    for inc in incomes:
        d = inc["date"]
        key = (d.year, d.month)
        aid = inc.get("account_id")
        monthly_income[key][aid] += inc["amount"]

    for t in transactions:
        d = t["date"]
        key = (d.year, d.month)
        aid = t.get("account_id")
        monthly_expense[key][aid] += t["amount"]

    # Inizializza i saldi correnti
    running_totals: dict[int | None, float] = {aid: opening for aid, opening in acc_id_to_opening.items()}
    running_totals[None] = 0.0 # Per transazioni senza conto associato
    
    # Determina il mese di partenza (il primo con attività o view_start)
    all_keys_with_activity = sorted(set(monthly_income.keys()) | set(monthly_expense.keys()))
    if not all_keys_with_activity:
        first_y, first_m = view_start.year, view_start.month
    else:
        first_y, first_m = all_keys_with_activity[0]
        if date(first_y, first_m, 1) > view_start:
            first_y, first_m = view_start.year, view_start.month

    capital_trend = []
    
    curr_y, curr_m = first_y, first_m
    while date(curr_y, curr_m, 1) <= end:
        m_key = (curr_y, curr_m)
        
        # Aggiorna i saldi di TUTTI i conti (inclusi quelli con ID None)
        # 1. Incomes
        for aid, amount in monthly_income.get(m_key, {}).items():
            running_totals[aid] = running_totals.get(aid, 0.0) + amount
        # 2. Expenses
        for aid, amount in monthly_expense.get(m_key, {}).items():
            running_totals[aid] = running_totals.get(aid, 0.0) - amount
        
        # Se siamo nel range di visualizzazione, aggiungi ai risultati
        if date(curr_y, curr_m, 1) >= view_start:
            total_balance = sum(running_totals.values())
            entry = {
                "month": _month_label(curr_y, curr_m),
                "total": round(total_balance, 2)
            }
            # Se Pro, aggiungiamo i dettagli per account (mappando ID -> Nome)
            if plan_type == "pro":
                for aid, bal in running_totals.items():
                    if aid is not None:
                        name = acc_id_to_name.get(aid, f"Conto {aid}")
                        entry[name] = round(bal, 2)
                    elif abs(bal) > 0.01:
                        # Mostra "Altro" solo se ha un saldo significativo
                        entry["Altro"] = round(bal, 2)
            
            capital_trend.append(entry)
            
        # Avanza al mese successivo
        curr_m += 1
        if curr_m > 12:
            curr_m = 1
            curr_y += 1

    return jsonify({
        "capital_trend": capital_trend,
        "plan_type": plan_type,
        "accounts": [a["name"] for a in accounts] if plan_type == "pro" else []
    })


@app.route("/api/analytics/budget-status")
@_tg_webapp_auth
def analytics_budget_status():
    """Ritorna lo stato budget per ogni categoria nel mese corrente (o specificato).
    
    Query params:
        month=YYYY-MM   (default: mese corrente)
    Richiede Pro — per Free ritorna errore con plan_type.
    """
    from flask import g
    from datetime import date

    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "budget_status": [],
        })

    month_str = request.args.get("month", "")
    if month_str:
        try:
            parts = month_str.split("-")
            target_year, target_month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            target_year, target_month = date.today().year, date.today().month
    else:
        target_year, target_month = date.today().year, date.today().month

    from calendar import monthrange
    month_start = date(target_year, target_month, 1)
    _, last_day = monthrange(target_year, target_month)
    month_end = date(target_year, target_month, last_day)

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(month_start, month_end)
        incomes = storage.fetch_income(month_start, month_end)
        categories = storage.get_categories()

    # Budget impostati
    budget_map = {c["name"]: (c.get("monthly_budget") or 0.0) for c in categories}
    
    # Speso per categoria
    spent_by_cat: dict[str, float] = defaultdict(float)
    for t in transactions:
        cat = t.get("category") or "Altro"
        spent_by_cat[cat] += t["amount"]

    # Solo categorie con budget
    budget_status = []
    for cat_name, budget in budget_map.items():
        if budget <= 0:
            continue
        spent = round(spent_by_cat.get(cat_name, 0.0), 2)
        percentage = round((spent / budget) * 100, 1) if budget > 0 else 0.0
        budget_status.append({
            "category": cat_name,
            "budget": round(budget, 2),
            "spent": spent,
            "remaining": round(max(budget - spent, 0), 2),
            "percentage": percentage,
        })

    # Ordina per % spesa decrescente
    budget_status.sort(key=lambda x: x["percentage"], reverse=True)

    # Totale entrate del mese
    total_income = round(sum(inc["amount"] for inc in incomes), 2)
    total_spent = round(sum(spent_by_cat.values()), 2)

    return jsonify({
        "budget_status": budget_status,
        "month": _month_label(target_year, target_month),
        "total_income": total_income,
        "total_spent": total_spent,
        "plan_type": plan_type,
    })


@app.route("/api/analytics/transactions")
@_tg_webapp_auth
def analytics_transactions():
    """Lista transazioni filtrabile per periodo, categoria, conto.
    
    Query params:
        start=YYYY-MM-DD   (default: 30 giorni fa)
        end=YYYY-MM-DD     (default: oggi)
        category=NAME      (filtro categoria, opzionale)
        account=NAME       (filtro conto, opzionale)
        limit=N            (default 50, max 50 Free / 500 Pro)
        offset=N           (default 0, paginazione)
    """
    from flask import g
    from datetime import date

    plan_type = _get_user_plan_type(g.chat_id)
    is_pro = plan_type == "pro"
    max_limit = 500 if is_pro else 50
    limit = min(int(request.args.get("limit", 50)), max_limit)
    offset = max(int(request.args.get("offset", 0)), 0)

    # Periodo: Free solo ultimi 30 giorni
    today = date.today()
    end_str = request.args.get("end", today.isoformat())
    try:
        end_date = date.fromisoformat(end_str)
    except (ValueError, TypeError):
        end_date = today

    if is_pro:
        thirty_days_ago = today - timedelta(days=30)
        start_str = request.args.get("start", thirty_days_ago.isoformat())
        try:
            start_date = date.fromisoformat(start_str)
        except (ValueError, TypeError):
            start_date = thirty_days_ago
    else:
        start_date = today - timedelta(days=30)

    category_filter = request.args.get("category", "").strip()
    account_filter = request.args.get("account", "").strip()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start_date, end_date)
        accounts = storage.fetch_accounts()

    acc_map = {a["id"]: a["name"] for a in accounts}

    # Arricchisci con nome account e categoria
    enriched = []
    for t in transactions:
        acc_name = acc_map.get(t.get("account_id"), "Altro")
        cat = t.get("category") or "Altro"
        
        if category_filter and cat.lower() != category_filter.lower():
            continue
        if account_filter and acc_name.lower() != account_filter.lower():
            continue
        
        d = t["date"]
        enriched.append({
            "id": t.get("id", 0),
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "name": t.get("name", ""),
            "amount": round(t["amount"], 2),
            "category": cat,
            "account": acc_name,
            "created_at": t.get("created_at") or "",
        })

    # Ordina per data decrescente, a parità di data dalla più recente (created_at desc)
    enriched.sort(key=lambda x: (x["date"], x["created_at"]), reverse=True)
    
    total_count = len(enriched)
    total_amount = round(sum(e["amount"] for e in enriched), 2)

    # Paginazione
    page = enriched[offset:offset + limit]

    return jsonify({
        "transactions": page,
        "total": total_count,
        "total_amount": total_amount,
        "offset": offset,
        "limit": limit,
        "plan_type": plan_type,
    })


@app.route("/api/analytics/top-merchants")
@_tg_webapp_auth
def analytics_top_merchants():
    """Top beneficiari/merchant per spesa totale.
    
    Query params:
        months=N   (default 3)
        limit=N    (default 5 Free, 20 Pro)
    """
    from flask import g

    plan_type = _get_user_plan_type(g.chat_id)
    is_pro = plan_type == "pro"
    max_months = 24 if is_pro else 3
    months = min(int(request.args.get("months", 3)), max_months)
    default_limit = 20 if is_pro else 5
    limit = min(int(request.args.get("limit", default_limit)), default_limit)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)

    # Aggrega per nome beneficiario
    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_cats: dict[str, str] = {}
    merchant_counts: dict[str, int] = defaultdict(int)

    for t in transactions:
        name = t.get("name", "Sconosciuto").strip() or "Sconosciuto"
        merchant_totals[name] += t["amount"]
        merchant_counts[name] += 1
        if name not in merchant_cats:
            merchant_cats[name] = t.get("category") or "Altro"

    # Top N
    top = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:limit]

    result = [
        {
            "name": name,
            "total": round(total, 2),
            "count": merchant_counts[name],
            "category": merchant_cats.get(name, "Altro"),
        }
        for name, total in top
    ]

    return jsonify({"merchants": result, "plan_type": plan_type})


@app.route("/api/analytics/savings-rate")
@_tg_webapp_auth
def analytics_savings_rate():
    """Tasso di risparmio mensile: (entrate - uscite) / entrate * 100.
    
    Richiede Pro — per Free ritorna errore con plan_type.
    """
    from flask import g

    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "savings_rate": [],
        })

    months = min(int(request.args.get("months", 6)), 24)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)
        incomes = storage.fetch_income(start, end)

    monthly_expenses: dict[tuple, float] = defaultdict(float)
    for t in transactions:
        d = t["date"]
        key = (d.year, d.month)
        monthly_expenses[key] += t["amount"]

    monthly_income: dict[tuple, float] = defaultdict(float)
    for inc in incomes:
        d = inc["date"]
        key = (d.year, d.month)
        monthly_income[key] += inc["amount"]

    all_keys = sorted(set(monthly_expenses) | set(monthly_income))
    
    savings_rate = []
    for key in all_keys:
        y, m = key
        inc = round(monthly_income.get(key, 0.0), 2)
        exp = round(monthly_expenses.get(key, 0.0), 2)
        savings = round(inc - exp, 2)
        rate = round((savings / inc) * 100, 1) if inc > 0 else 0.0
        savings_rate.append({
            "month": _month_label(y, m),
            "income": inc,
            "expenses": exp,
            "savings": savings,
            "rate": rate,
        })

    return jsonify({"savings_rate": savings_rate, "plan_type": plan_type})


@app.route("/api/analytics/month-comparison")
@_tg_webapp_auth
def analytics_month_comparison():
    """Confronto spese per categoria: mese corrente vs mese precedente vs media 3 mesi.
    
    Richiede Pro — per Free ritorna errore con plan_type.
    """
    from flask import g
    from datetime import date
    from calendar import monthrange

    plan_type = _get_user_plan_type(g.chat_id)
    if plan_type != "pro":
        return jsonify({
            "error": "Funzionalita' riservata agli utenti Pro",
            "plan_type": "free",
            "comparisons": [],
        })

    today = date.today()
    current_year, current_month = today.year, today.month

    # Mese corrente
    cur_start = date(current_year, current_month, 1)
    _, last_day = monthrange(current_year, current_month)
    cur_end = date(current_year, current_month, min(today.day, last_day))

    # 4 mesi di storico per calcolare mese scorso e media 3m
    history_start = _start_date_for_months(4)

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(history_start, cur_end)

    # Aggrega per (anno, mese, categoria)
    monthly_cat: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        d = t["date"]
        key = (d.year, d.month)
        cat = t.get("category") or "Altro"
        monthly_cat[key][cat] += t["amount"]

    # Mese corrente
    cur_key = (current_year, current_month)
    cur_spending = monthly_cat.get(cur_key, {})

    # Mese precedente
    if current_month == 1:
        prev_key = (current_year - 1, 12)
    else:
        prev_key = (current_year, current_month - 1)
    prev_spending = monthly_cat.get(prev_key, {})

    # Media ultimi 3 mesi completi (escludendo il corrente)
    all_keys = sorted(monthly_cat.keys())
    past_keys = [k for k in all_keys if k != cur_key][-3:]
    
    avg_spending: dict[str, float] = {}
    if past_keys:
        for k in past_keys:
            for cat, amount in monthly_cat[k].items():
                avg_spending[cat] = avg_spending.get(cat, 0.0) + amount
        n_months = len(past_keys)
        for cat in avg_spending:
            avg_spending[cat] = round(avg_spending[cat] / n_months, 2)

    # Costruisci il confronto
    all_cats = set(cur_spending) | set(prev_spending) | set(avg_spending)
    comparisons = []
    for cat in sorted(all_cats):
        cur_val = round(cur_spending.get(cat, 0.0), 2)
        prev_val = round(prev_spending.get(cat, 0.0), 2)
        avg_val = round(avg_spending.get(cat, 0.0), 2)
        
        change_pct = round(((cur_val - prev_val) / prev_val) * 100, 1) if prev_val > 0 else 0.0
        
        comparisons.append({
            "category": cat,
            "current_month": cur_val,
            "last_month": prev_val,
            "avg_3m": avg_val,
            "change_pct": change_pct,
        })

    return jsonify({"comparisons": comparisons, "plan_type": plan_type})


# ---------------------------------------------------------------------------
# API Reports — storico report web
# ---------------------------------------------------------------------------

@app.route("/api/reports/<share_token>", methods=["GET"])
def api_get_report_by_token(share_token: str):
    """Endpoint pubblico: restituisce un report tramite share_token (no auth richiesta)."""
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id="")
        report = storage.get_report_by_token(share_token)
    if not report:
        return jsonify({"error": "Report non trovato"}), 404
    return jsonify(report)


@app.route("/api/reports/generate", methods=["POST"])
@_tg_webapp_auth
@limiter.limit("5 per minute")
def api_generate_report():
    """Endpoint autenticato: genera on-demand il report weekly o monthly per l'utente
    corrente, riusando la stessa logica della routine automatica (bot.py). Se l'utente
    ha anche Telegram collegato, il messaggio viene inviato anche lì."""
    from flask import g

    body = request.get_json(silent=True) or {}
    report_type = body.get("type")
    if report_type not in ("weekly", "monthly"):
        return jsonify({"error": "type deve essere 'weekly' o 'monthly'"}), 400

    chat_id = g.chat_id
    telegram_connected = not str(chat_id).startswith("web_")

    import asyncio

    try:
        if report_type == "weekly":
            from telegram import Bot
            import bot as bot_module

            tg_bot = Bot(token=Config.TELEGRAM_BOT_TOKEN) if telegram_connected else None
            share_token = asyncio.run(bot_module._build_and_send_weekly_plan(chat_id=chat_id, bot=tg_bot))
        else:
            if store.get_user_plan(chat_id)["tokens_remaining"] < 5000:
                return jsonify({"error": "Token mensili insufficienti per generare il report mensile."}), 402

            import main as main_module

            target_year, target_month = main_module._resolve_default_target_month(date.today())
            share_token = asyncio.run(main_module.run_agent(
                target_year, target_month, dry_run=False, chat_id=chat_id, shared_store=store,
            ))
    except Exception as e:
        logger.exception("Errore generazione report %s on-demand per %s: %s", report_type, chat_id, e)
        return jsonify({"error": "Generazione del report fallita. Riprova tra poco."}), 500

    if not share_token:
        return jsonify({"error": "Nessun dato disponibile per generare il report di questo periodo."}), 422

    return jsonify({"ok": True, "share_token": share_token})


@app.route("/api/reports", methods=["GET"])
@_tg_webapp_auth
def api_get_reports_for_user():
    """Endpoint autenticato: lista report dell'utente corrente."""
    from flask import g
    limit = min(int(request.args.get("limit", 24)), 100)
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        reports = storage.get_reports_for_user(user_id=g.chat_id, limit=limit)
    # Omette text_content e report_data per tenere la lista leggera
    summary = [
        {
            "id": r["id"],
            "report_type": r["report_type"],
            "report_date": r["report_date"],
            "share_token": r["share_token"],
            "created_at": r["created_at"],
        }
        for r in reports
    ]
    return jsonify({"reports": summary})


# ---------------------------------------------------------------------------
# /api/space — CRUD completo per la pagina "Il mio Spazio"
# ---------------------------------------------------------------------------

def _pg_or_401(s, chat_id):
    """Restituisce (PostgresStorage, None) o (None, response 400) se backend != postgres."""
    from src.user_store import User
    from src.storage import rls
    # La RLS si applica al primo statement della transazione (listener after_begin):
    # va impostata PRIMA di qualunque query su questa sessione, altrimenti la query
    # su User qui sotto apre la transazione senza app.user_id e ogni successivo
    # INSERT/UPDATE sulle tabelle protette da RLS viene rifiutato dal database.
    rls.bind_user(s, chat_id)
    user = s.query(User).filter_by(chat_id=chat_id).first()
    if not user or user.storage_backend != "postgres":
        return None, (jsonify({"error": "Solo backend PostgreSQL supportato"}), 400)
    return PostgresStorage(session=s, user_id=chat_id), None


# ── Accounts ─────────────────────────────────────────────────────────────────

@app.route("/api/space/accounts", methods=["GET"])
@_tg_webapp_auth
def space_accounts_list():
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"accounts": pg.fetch_accounts()})


@app.route("/api/space/accounts", methods=["POST"])
@_tg_webapp_auth
def space_accounts_create():
    from flask import g
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_account(
            name,
            initial_balance=float(data.get("initial_balance") or 0),
            account_type=data.get("account_type") or None,
        )
        return jsonify(result), 201


@app.route("/api/space/accounts/<int:account_id>", methods=["PUT"])
@_tg_webapp_auth
def space_accounts_update(account_id: int):
    from flask import g
    data = request.json or {}
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.update_account(
            account_id,
            name=data.get("name") or None,
            balance=float(data["balance"]) if data.get("balance") not in (None, "") else None,
            account_type=data.get("account_type") or None,
        )
        if result is None:
            return jsonify({"error": "Conto non trovato"}), 404
        return jsonify(result)


@app.route("/api/space/accounts/<int:account_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_accounts_delete(account_id: int):
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_account(account_id)
        if not ok:
            return jsonify({"error": "Conto non trovato"}), 404
        return jsonify({"status": "ok"})


# ── Transfers ────────────────────────────────────────────────────────────────

@app.route("/api/space/transfers", methods=["GET"])
@_tg_webapp_auth
def space_transfers_list():
    from flask import g
    from datetime import date as _date, datetime as _dt
    today = _date.today()
    start = request.args.get("start", _date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    try:
        start_d = _dt.strptime(start, "%Y-%m-%d").date()
        end_d = _dt.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items = pg.fetch_transfers(start_d, end_d)
        for item in items:
            if hasattr(item.get("date"), "isoformat"):
                item["date"] = item["date"].isoformat()
        return jsonify({"transfers": items})


@app.route("/api/space/transfers", methods=["POST"])
@_tg_webapp_auth
def space_transfers_create():
    from flask import g
    from datetime import datetime as _dt
    data = request.json or {}
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Il campo 'amount' è obbligatorio ed è un numero"}), 400
    if amount <= 0:
        return jsonify({"error": "L'importo deve essere positivo"}), 400
    from_account_id = data.get("from_account_id")
    to_account_id = data.get("to_account_id")
    if not from_account_id or not to_account_id:
        return jsonify({"error": "I campi 'from_account_id' e 'to_account_id' sono obbligatori"}), 400
    if str(from_account_id) == str(to_account_id):
        return jsonify({"error": "Il conto di origine e di destinazione devono essere diversi"}), 400
    try:
        transfer_date = _dt.strptime(data.get("date") or _dt.today().strftime("%Y-%m-%d"), "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        try:
            result = pg.create_transfer(
                transfer_date=transfer_date,
                amount=amount,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                name=(data.get("name") or "").strip() or None,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if hasattr(result.get("date"), "isoformat"):
            result["date"] = result["date"].isoformat()
        return jsonify(result), 201


# ── Categories ────────────────────────────────────────────────────────────────

@app.route("/api/space/categories", methods=["GET"])
@_tg_webapp_auth
def space_categories_list():
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"categories": pg.fetch_categories_full()})


@app.route("/api/space/categories/suggestions", methods=["GET"])
@_tg_webapp_auth
def space_categories_suggestions():
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"suggestions": pg.get_budget_suggestions()})


@app.route("/api/space/categories/<int:cat_id>/accept-suggestion", methods=["POST"])
@_tg_webapp_auth
def space_categories_accept_suggestion(cat_id: int):
    from flask import g
    data = request.json or {}
    suggested = data.get("suggested_budget")
    if suggested is None:
        return jsonify({"error": "suggested_budget obbligatorio"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.update_category(cat_id, monthly_budget=float(suggested))
        if result is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify(result)


@app.route("/api/space/categories", methods=["POST"])
@_tg_webapp_auth
def space_categories_create():
    from flask import g
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        existing = {n.lower() for n in pg.get_category_names()}
        if name.lower() in existing:
            return jsonify({"error": f"Categoria '{name}' già esistente"}), 409
        monthly_budget = float(data["monthly_budget"]) if data.get("monthly_budget") not in (None, "") else None
        result = pg.create_category(name, monthly_budget=monthly_budget)
        return jsonify(result), 201


@app.route("/api/space/categories/<int:cat_id>", methods=["PUT"])
@_tg_webapp_auth
def space_categories_update(cat_id: int):
    from flask import g
    data = request.json or {}
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        monthly_budget = float(data["monthly_budget"]) if data.get("monthly_budget") not in (None, "") else None
        result = pg.update_category(cat_id, name=data.get("name") or None, monthly_budget=monthly_budget)
        if result is None:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify(result)


@app.route("/api/space/categories/<int:cat_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_categories_delete(cat_id: int):
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_category(cat_id)
        if not ok:
            return jsonify({"error": "Categoria non trovata"}), 404
        return jsonify({"status": "ok"})


# ── Subscriptions ─────────────────────────────────────────────────────────────

@app.route("/api/space/subscriptions", methods=["GET"])
@_tg_webapp_auth
def space_subscriptions_list():
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        return jsonify({"subscriptions": pg.fetch_subscriptions_with_account_name()})


@app.route("/api/space/subscriptions", methods=["POST"])
@_tg_webapp_auth
def space_subscriptions_create():
    from flask import g
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Il campo 'name' è obbligatorio"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_subscription(
            name,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            last_billed=data.get("last_billed") or None,
            sub_type=data.get("sub_type") or None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
        )
        return jsonify(result), 201


@app.route("/api/space/subscriptions/<int:sub_id>", methods=["PUT"])
@_tg_webapp_auth
def space_subscriptions_update(sub_id: int):
    from flask import g
    data = request.json or {}
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        from datetime import datetime as _dt
        last_billed = None
        if data.get("last_billed"):
            try:
                last_billed = _dt.strptime(data["last_billed"], "%Y-%m-%d").date()
            except ValueError:
                pass
        result = pg.update_subscription(
            sub_id,
            name=data.get("name") or None,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            last_billed=last_billed,
            sub_type=data.get("sub_type") or None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
        )
        if result is None:
            return jsonify({"error": "Abbonamento non trovato"}), 404
        return jsonify(result)


@app.route("/api/space/subscriptions/<int:sub_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_subscriptions_delete(sub_id: int):
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_subscription(sub_id)
        if not ok:
            return jsonify({"error": "Abbonamento non trovato"}), 404
        return jsonify({"status": "ok"})


# ── Expenses ──────────────────────────────────────────────────────────────────

@app.route("/api/space/expenses", methods=["GET"])
@_tg_webapp_auth
def space_expenses_list():
    from flask import g
    from datetime import date as _date
    today = _date.today()
    start = request.args.get("start", _date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = int(request.args.get("offset", 0))
    try:
        from datetime import datetime as _dt
        start_d = _dt.strptime(start, "%Y-%m-%d").date()
        end_d = _dt.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    search = request.args.get("search") or None
    category_id = int(request.args.get("category_id")) if request.args.get("category_id") else None
    account_id_f = int(request.args.get("account_id")) if request.args.get("account_id") else None
    sort_by = request.args.get("sort_by", "date")
    if sort_by not in ("date", "amount", "name"):
        sort_by = "date"
    sort_dir = request.args.get("sort_dir", "desc")
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items, total = pg.fetch_expenses_paginated(
            start_d, end_d, limit=limit, offset=offset,
            search=search, category_id=category_id, account_id=account_id_f,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return jsonify({"expenses": items, "total": total})


@app.route("/api/space/expenses", methods=["POST"])
@_tg_webapp_auth
def space_expenses_create():
    from flask import g
    from datetime import datetime as _dt
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name or not data.get("amount") or not data.get("date"):
        return jsonify({"error": "name, amount e date sono obbligatori"}), 400
    try:
        exp_date = _dt.strptime(data["date"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_expense(
            expense_date=exp_date,
            amount=float(data["amount"]),
            name=name,
            category_name=data.get("category") or "",
            account_id=data.get("account_id"),
        )
        return jsonify(result), 201


@app.route("/api/space/expenses/<int:expense_id>", methods=["PUT"])
@_tg_webapp_auth
def space_expenses_update(expense_id: int):
    from flask import g
    from datetime import datetime as _dt
    data = request.json or {}
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        exp_date = None
        if data.get("date"):
            try:
                exp_date = _dt.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Formato data non valido"}), 400
        result = pg.update_expense(
            expense_id,
            name=data.get("name") or None,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            date=exp_date,
            category_id=int(data["category_id"]) if data.get("category_id") else None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
        )
        if result is None:
            return jsonify({"error": "Spesa non trovata"}), 404
        return jsonify(result)


@app.route("/api/space/expenses/<int:expense_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_expenses_delete(expense_id: int):
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_expense(expense_id)
        if not ok:
            return jsonify({"error": "Spesa non trovata"}), 404
        return jsonify({"status": "ok"})


# ── Incomes ───────────────────────────────────────────────────────────────────

@app.route("/api/space/incomes", methods=["GET"])
@_tg_webapp_auth
def space_incomes_list():
    from flask import g
    from datetime import date as _date
    today = _date.today()
    start = request.args.get("start", _date(today.year, today.month, 1).isoformat())
    end = request.args.get("end", today.isoformat())
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = int(request.args.get("offset", 0))
    try:
        from datetime import datetime as _dt
        start_d = _dt.strptime(start, "%Y-%m-%d").date()
        end_d = _dt.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido (YYYY-MM-DD)"}), 400
    search = request.args.get("search") or None
    income_type_f = request.args.get("income_type") or None
    account_id_f = int(request.args.get("account_id")) if request.args.get("account_id") else None
    sort_by = request.args.get("sort_by", "date")
    if sort_by not in ("date", "amount", "name"):
        sort_by = "date"
    sort_dir = request.args.get("sort_dir", "desc")
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        items, total = pg.fetch_incomes_paginated(
            start_d, end_d, limit=limit, offset=offset,
            search=search, income_type=income_type_f, account_id=account_id_f,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        return jsonify({"incomes": items, "total": total})


@app.route("/api/space/incomes", methods=["POST"])
@_tg_webapp_auth
def space_incomes_create():
    from flask import g
    from datetime import datetime as _dt
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name or not data.get("amount") or not data.get("date"):
        return jsonify({"error": "name, amount e date sono obbligatori"}), 400
    try:
        inc_date = _dt.strptime(data["date"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato data non valido"}), 400
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        result = pg.create_income(
            income_date=inc_date,
            amount=float(data["amount"]),
            name=name,
            account_id=data.get("account_id"),
            income_type=data.get("income_type") or None,
        )
        return jsonify(result), 201


@app.route("/api/space/incomes/<int:income_id>", methods=["PUT"])
@_tg_webapp_auth
def space_incomes_update(income_id: int):
    from flask import g
    from datetime import datetime as _dt
    data = request.json or {}
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        inc_date = None
        if data.get("date"):
            try:
                inc_date = _dt.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Formato data non valido"}), 400
        result = pg.update_income(
            income_id,
            name=data.get("name") or None,
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            date=inc_date,
            income_type=data.get("income_type") or None,
            account_id=int(data["account_id"]) if data.get("account_id") else None,
        )
        if result is None:
            return jsonify({"error": "Entrata non trovata"}), 404
        return jsonify(result)


@app.route("/api/space/incomes/<int:income_id>", methods=["DELETE"])
@_tg_webapp_auth
def space_incomes_delete(income_id: int):
    from flask import g
    with store.Session() as s:
        pg, err = _pg_or_401(s, g.chat_id)
        if err:
            return err
        ok = pg.delete_income(income_id)
        if not ok:
            return jsonify({"error": "Entrata non trovata"}), 404
        return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
