import os
import re
import sys
import json
import logging
import threading
from pathlib import Path
from functools import wraps

logger = logging.getLogger(__name__)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psutil
from datetime import datetime, timedelta
import requests
from notion_client import Client as NotionClient

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import Config
from src.user_store import UserStore, User, DailyUsage, DailyMetrics, Feedback
from src.notion_client import NotionFinanceClient
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.workspace_bootstrapper import bootstrap_workspace
from src.category_sync import refresh_category_averages

# Inizializza l'app Flask
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(24)

@app.after_request
def skip_ngrok_interstitial(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

# Inizializza la connessione allo storage SQLite
store = UserStore(db_url=Config.DATABASE_URL)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_logged_in"):
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


@app.route("/login", methods=["GET", "POST"])
def web_login():
    """Login web con email e password."""
    if session.get("logged_in"):
        return redirect(url_for("setup_form"))

    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        user = store.verify_password(email, password)
        if user:
            session["user_logged_in"] = True
            session["chat_id"] = user.chat_id
            reg_token = store.create_oauth_session(user.chat_id)
            return redirect(url_for("setup_form") + f"?reg_token={reg_token}")
        error = "Email o password errati."

    return render_template("login.html", error=error)


@app.route("/logout")
def web_logout():
    """Logout web."""
    session.clear()
    return redirect(url_for("web_login"))


# --- API e Utilità ---
def get_system_metrics():
    """Recupera l'utilizzo di risorse della macchina."""
    # RAM
    vmem = psutil.virtual_memory()
    # CPU (interval=None è essenziale per non causare blocchi o lag del processo su alcuni OS)
    cpu = psutil.cpu_percent(interval=None)
    
    # DB Size
    db_path = Config.DATABASE_URL.replace("sqlite:///", "")
    db_size = 0
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path) / (1024 * 1024) # MB
        
    return {
        "cpu_percent": cpu,
        "ram_percent": vmem.percent,
        "ram_used_gb": round(vmem.used / (1024**3), 2),
        "db_size_mb": round(db_size, 2)
    }

# --- Rotte Web (UI) ---

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        password = request.form.get("password")
        if password == Config.DASHBOARD_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("index"))
        else:
            error = "Password amministratore errata!"
            
    return render_template("login.html", admin_mode=True, error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

@app.route("/")
@admin_required
def index():
    sys_metrics = get_system_metrics()

    with store.Session() as s:
        # Statistiche utenti
        users_count = s.query(User).count()
        active_users = s.query(User).filter(User.is_active == True).count()
        
        # Statistiche feedback
        unread_feedback = s.query(Feedback).filter(Feedback.status == "unread").count()
        
        # Recupera daily usage degli ultimi 10 giorni
        ten_days_ago = datetime.utcnow().date() - timedelta(days=10)
        daily_stats = s.query(DailyUsage).filter(DailyUsage.usage_date >= ten_days_ago).all()
        
        # Aggrega dati per il grafico (Date -> totali)
        chart_data = {}
        for x in range(10):
            d = ten_days_ago + timedelta(days=x)
            chart_data[d.isoformat()] = {"text": 0, "voice": 0, "photo": 0}
            
        for stat in daily_stats:
            d_str = stat.usage_date.isoformat()
            if d_str in chart_data:
                chart_data[d_str]["text"] += stat.text_count
                chart_data[d_str]["voice"] += stat.voice_count
                chart_data[d_str]["photo"] += stat.photo_count
            
        labels = list(chart_data.keys())
        data_text = [v["text"] for v in chart_data.values()]
        data_voice = [v["voice"] for v in chart_data.values()]
        data_photo = [v["photo"] for v in chart_data.values()]
        
        # --- AI SaaS Metrics Calculation ---
        total_messages = sum(data_text) + sum(data_voice) + sum(data_photo)
        avg_msg_per_user = round(total_messages / active_users, 1) if active_users > 0 else 0
        api_cost_estimate = round(total_messages * 0.0015, 2)  # da calcolare precisamente in secondo momento

        # GCR e Fallback Rate: calcolati dai dati reali degli ultimi 10 giorni
        ai_metrics = s.query(DailyMetrics).filter(DailyMetrics.metrics_date >= ten_days_ago).all()
        total_completions = sum(m.goal_completions or 0 for m in ai_metrics)
        total_fallbacks = sum(m.fallbacks or 0 for m in ai_metrics)
        total_ai_interactions = total_completions + total_fallbacks
        if total_ai_interactions > 0:
            goal_completion_rate = round(total_completions / total_ai_interactions * 100, 1)
            fallback_rate = round(total_fallbacks / total_ai_interactions * 100, 1)
        else:
            goal_completion_rate = None  # nessun dato ancora
            fallback_rate = None

    return render_template(
        "index.html", 
        sys=sys_metrics,
        users_count=users_count,
        active_users=active_users,
        unread_feedback=unread_feedback,
        chart_labels=labels,
        chart_text=data_text,
        chart_voice=data_voice,
        chart_photo=data_photo,
        avg_msg_per_user=avg_msg_per_user,
        api_cost_estimate=api_cost_estimate,
        goal_completion_rate=goal_completion_rate,
        fallback_rate=fallback_rate
    )

@app.route("/users")
@admin_required
def users_list():
    with store.Session() as s:
        users = s.query(User).order_by(User.created_at.desc()).all()
    return render_template("users.html", users=users)

@app.route("/api/toggle-user/<chat_id>", methods=["POST"])
@admin_required
def toggle_user(chat_id):
    with store.Session() as s:
        user = s.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.is_active = not user.is_active
            s.commit()
            return jsonify({"status": "ok", "new_state": user.is_active})
    return jsonify({"error": "User not found"}), 404

@app.route("/feedbacks")
@admin_required
def feedbacks_list():
    with store.Session() as s:
        fbs = s.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return render_template("feedbacks.html", feedbacks=fbs)

@app.route("/api/resolve-feedback/<int:fb_id>", methods=["POST"])
@admin_required
def resolve_feedback(fb_id):
    with store.Session() as s:
        fb = s.query(Feedback).filter(Feedback.id == fb_id).first()
        if fb:
            fb.status = "resolved" if fb.status == "unread" else "unread"
            s.commit()
            return jsonify({"status": "ok", "new_state": fb.status})
    return jsonify({"error": "Feedback not found"}), 404

@app.route("/logs")
@admin_required
def logs_viewer():
    log_file = Config.LOG_DIR / "agent.log"
    log_lines = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            # Raccogli le ultime 100 righe
            lines = f.readlines()
            log_lines = lines[-100:]
            
    return render_template("logs.html", log_lines=log_lines)

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
            requests.post(telegram_url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as tg_err:
            print(f"[OAuth-bg] Errore invio Telegram: {tg_err}")

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
                print(f"[OAuth-bg] Errore salvataggio schema {db_key}: {schema_err}")

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
                print(f"[OAuth-bg] Errore bootstrap workspace: {bootstrap_err}")

        # 6. Notifica finale
        if len(valid_discovered) != 7:
            found_count = len(valid_discovered)

            if found_count == 0:
                # Nessun DB trovato: l'integrazione non ha accesso al template
                report_msg = (
                    "⚠️ <b>Nessun database trovato</b>\n\n"
                    "L'integrazione non riesce a vedere i database del template Moneo.\n\n"
                    "👉 <b>Cosa fare:</b>\n"
                    "1. Apri Notion → cerca la pagina <b>Dashboard Tracky Finance</b>\n"
                    "2. Clicca su <b>...</b> in alto a destra → <b>Connect to</b> → seleziona <b>Traky Finance Agent</b>\n"
                    "3. Riapri <b>/registrati</b> e riprova\n\n"
                    "<i>Assicurati di condividere la pagina root e tutte le sotto-pagine con l'integrazione.</i>"
                )
            else:
                report_msg = (
                    f"⚠️ <b>Configurazione parziale ({found_count}/7)</b>\n\n"
                    "Ho trovato alcuni database ma ne mancano altri.\n\n"
                    "👉 <b>Cosa fare:</b>\n"
                    "1. Assicurati che nel template ci siano tutti i <b>Database</b> (non solo pagine).\n"
                    "2. Condividi la pagina root <b>Dashboard Tracky Finance</b> con l'integrazione.\n"
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

        report_msg = "🎊 <b>TRAKY È PRONTO ALL'AZIONE!</b>\n\nHo scansionato il tuo Notion e collegato i database:\n"
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
            report_msg += (
                "\n\n👇 <b>Inizia a usare Moneo configurando il tuo spazio:</b>\n"
                "1️⃣ Clicca sul pulsante qui sotto.\n"
                "2️⃣ Aggiungi i tuoi <b>Conti</b> (es. Conto Corrente, Contanti) e imposta il saldo iniziale.\n"
                "3️⃣ Personalizza le tue <b>Categorie</b> di spesa ed eventuali budget.\n"
                "4️⃣ Inserisci i tuoi <b>Abbonamenti</b> per tenerne traccia automaticamente."
            )
            reg_token_miniapp = store.create_oauth_session(chat_id)
            miniapp_url = f"{Config.WEBAPP_BASE_URL}/setup?reg_token={reg_token_miniapp}"
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
                })
            except Exception as tg_err:
                print(f"[OAuth-bg] Errore invio messaggio finale: {tg_err}")

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
            requests.post(telegram_url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as tg_err:
            print(f"[Postgres-bg] Errore invio Telegram: {tg_err}")

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
            "🎊 <b>MONEO È PRONTO!</b>\n\n"
            "Ho creato il tuo spazio personale nel database interno PostgreSQL.\n"
        )
        bootstrap_msg = bootstrap_result.to_telegram_message()
        if bootstrap_msg:
            report_msg += "\n" + bootstrap_msg

        report_msg += (
            "\n\n👇 <b>Inizia a usare Moneo configurando il tuo spazio:</b>\n"
            "1️⃣ Clicca sul pulsante qui sotto.\n"
            "2️⃣ Aggiungi i tuoi <b>Conti</b> (es. Conto Corrente, Contanti) e imposta il saldo iniziale.\n"
            "3️⃣ Personalizza le tue <b>Categorie</b> di spesa ed eventuali budget.\n"
            "4️⃣ Inserisci i tuoi <b>Abbonamenti</b> per tenerne traccia automaticamente."
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
            })
        except Exception as tg_err:
            print(f"[Postgres-bg] Errore invio messaggio finale: {tg_err}")

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
        )
    except Exception:
        pass

    threading.Thread(target=_process_postgres_background, args=(chat_id,), daemon=True).start()
    return redirect("https://t.me/NotionFinaceBot")


@app.route("/auth/notion/callback")
def auth_notion_callback():
    """Riceve il codice da Notion, scambia il token e avvia il setup in background."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h1>Errore di autorizzazione Notion</h1><p>{error}</p>"

    if not code or not state:
        return "<h1>Parametri mancanti</h1>", 400

    # 1. Verifica stato OAuth
    chat_id = store.get_and_delete_oauth_session(state)
    if not chat_id:
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
        )
        if not response.ok:
            return f"<h1>Errore scambio token</h1><p>{response.text}</p>", 500

        auth_data = response.json()
        access_token = auth_data.get("access_token")
        workspace_id = auth_data.get("workspace_id")
        template_page_id = auth_data.get("duplicated_template_id")
    except Exception as e:
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
        )
    except Exception:
        pass  # Non bloccare se Telegram è irraggiungibile

    t = threading.Thread(
        target=_process_oauth_background,
        args=(access_token, workspace_id, chat_id, template_page_id),
        daemon=False,  # NON daemon: il Flask reloader non deve killarlo durante la discovery
    )
    t.start()

    return redirect("https://t.me/NotionFinaceBot")

# --- SETUP MINI APP (Fase 6) ---

@app.route("/setup")
def setup_form():
    """Mostra il form dinamico per il setup iniziale."""
    reg_token = request.args.get("reg_token")
    if not reg_token:
        return "<h1>Accesso negato</h1><p>Manca il token di configurazione.</p>", 403
        
    with store.Session() as s:
        from src.user_store import OAuthSession, User
        sess = s.query(OAuthSession).filter_by(state=reg_token).first()
        if not sess:
             # Fallback: controlliamo se l'utente esiste già ed è in stato setup
             # Altrimenti diamo errore
             return "<h1>Sessione scaduta</h1><p>Ricomincia il setup dal bot.</p>", 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return "<h1>Utente non trovato</h1><p>Esegui prima /registrati dal bot.</p>", 403

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
            return "<h1>Utente non autorizzato</h1><p>Devi prima connettere Notion con /registrati.</p>", 403

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
                print(f"[Setup] Errore recupero schemi live da Notion: {e}")

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
                print(f"[Setup] Errore parsing schema {db_key}: {e}")

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
            print(f"[Setup] fetch_accounts fallito: {e}")
        try:
            nc_cat = NotionFinanceClient(
                api_key=user.notion_access_token,
                categories_db_id=user.categories_db_id,
                db_schemas=schemas,
            )
            available_categories = nc_cat.fetch_categories()
        except Exception as e:
            print(f"[Setup] fetch_categories da Notion fallito: {e}")
            try:
                from src.storage.models import UserCategory
                cat_rows = s.query(UserCategory).filter_by(user_id=user.chat_id).all()
                available_categories = [
                    {"id": r.notion_page_id or str(r.id), "name": r.name, "monthly_budget": r.monthly_budget}
                    for r in cat_rows
                ]
            except Exception as e2:
                print(f"[Setup] fetch_categories da DB fallito: {e2}")

        return render_template("setup_miniapp.html",
                               backend="notion",
                               schemas=schemas,
                               reg_token=reg_token,
                               user_name=user.username or "Utente",
                               available_accounts=available_accounts,
                               available_categories=available_categories,
                               available_subscriptions=[],
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
            return jsonify({"error": "Invalid session"}), 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # --- Branch PostgreSQL: payload piatto, creazione diretta via PostgresStorage ---
        if user.storage_backend == "postgres":
            pg_storage = PostgresStorage(session=s, user_id=user.chat_id)
            errors: list[str] = []
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
                    errors.append(f"Errore categoria '{name}': {e}")

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
                    errors.append(f"Errore account '{name}': {e}")

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
                                f"Ho creato {created_count} elementi nel database interno.\n\n"
                                f"Ora puoi iniziare a scrivermi le tue spese!"
                            ),
                            "parse_mode": "HTML"
                        })
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
            print(f"[DEBUG] schema {k} → properties keys: {list(v.get('properties', {}).keys())}, mapped: {v.get('mapped')}")

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
                print(f"[DEBUG] account prop_data keys: {list(prop_data.keys())}")
                print(f"[DEBUG] account prop_data: {prop_data}")
                name = _extract_name(prop_data)
                acc_type = _extract_select(prop_data, Config.NOTION_ACCOUNTS_COL_TYPE)
                print(f"[DEBUG] account name='{name}', type='{acc_type}' (cercato con chiave '{Config.NOTION_ACCOUNTS_COL_TYPE}')")
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
                    })
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
            return jsonify({"error": "Invalid session"}), 403

        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

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
            return jsonify({"error": "Invalid session"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

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
            return jsonify({"error": "Invalid session"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

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
            return jsonify({"error": "Invalid session"}), 403
        user = s.query(User).filter_by(chat_id=sess.chat_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

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

            return jsonify({"status": "ok", "entity": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


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

    params: dict[str, str] = {}
    received_hash: str | None = None
    for part in init_data_raw.split("&"):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        if k == "hash":
            received_hash = v
        else:
            params[k] = v

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
    """Decorator: legge X-Telegram-Init-Data header, valida HMAC, inietta g.chat_id."""
    from flask import g
    @wraps(f)
    def decorated(*args, **kwargs):
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not init_data:
            return jsonify({"error": "Missing Telegram auth"}), 401
        parsed = _validate_telegram_init_data(init_data)
        if not parsed or not parsed["chat_id"]:
            return jsonify({"error": "Invalid Telegram auth"}), 401
        g.chat_id = parsed["chat_id"]
        return f(*args, **kwargs)
    return decorated


def _month_label(year: int, month: int) -> str:
    return f"{month_abbr[month]} {str(year)[-2:]}"


def _start_date_for_months(months: int):
    from datetime import date
    today = date.today()
    # torna all'inizio del mese N mesi fa
    m = today.month - months
    y = today.year + m // 12
    m = m % 12
    if m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


@app.route("/api/analytics/overview")
@_tg_webapp_auth
def analytics_overview():
    """Ritorna risparmio mensile e spesa mensile per account negli ultimi N mesi."""
    from flask import g
    months = min(int(request.args.get("months", 6)), 6)
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

    return jsonify({"savings": savings, "totals_by_account": totals_by_account})


@app.route("/api/analytics/categories-expense")
@_tg_webapp_auth
def analytics_categories_expense():
    """Ritorna spese per categoria: storico mensile e medie per ultimi N mesi."""
    from flask import g
    months = min(int(request.args.get("months", 6)), 6)
    start = _start_date_for_months(months)
    from datetime import date
    end = date.today()

    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        transactions = storage.fetch_all_transactions(start, end)
        categories = storage.get_categories()

    budget_map = {c["name"]: c.get("monthly_budget") for c in categories}

    # Aggrega per (anno, mese, categoria)
    monthly_cat: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        d = t["date"]
        key = (d.year, d.month)
        cat = t.get("category") or "Altro"
        monthly_cat[key][cat] += t["amount"]

    all_keys = sorted(monthly_cat.keys())

    by_category = []
    for key in all_keys:
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

    return jsonify({"by_category": by_category, "averages": averages})


@app.route("/api/analytics/income")
@_tg_webapp_auth
def analytics_income():
    """Ritorna storico entrate mensili negli ultimi N mesi."""
    from flask import g
    months = min(int(request.args.get("months", 6)), 6)
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
    return jsonify({"monthly": result})


@app.route("/api/analytics/wealth")
@_tg_webapp_auth
def analytics_wealth():
    """Ritorna saldo corrente per account (capitale totale)."""
    from flask import g
    with store.Session() as s:
        storage = PostgresStorage(session=s, user_id=g.chat_id)
        accounts = storage.fetch_accounts()

    result = [
        {"name": a["name"], "balance": round(a["balance"] or 0.0, 2)}
        for a in accounts
        if (a.get("balance") or 0.0) > 0
    ]
    return jsonify({"accounts": result})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
