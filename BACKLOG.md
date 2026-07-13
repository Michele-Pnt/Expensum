# Backlog

## Da fare

- **Tradurre l'app completa in EN** (dashboard, chat, onboarding, impostazioni, abbonamenti,
  analytics, reports, feedback, tour guidato) — estensione dell'i18n con next-intl già
  impostato per le pagine pubbliche (`frontend/src/app/[locale]/`: landing, come-funziona-moneo,
  privacy, terms, cookies). Richiede: estrazione di tutte le stringhe hardcoded nei componenti
  dell'app in `frontend/src/messages/{it,en}.json`, inclusi i contenuti generati lato server
  (report Telegram, notifiche, email). Da completare prima del lancio ufficiale — vedi task
  ClickUp collegato.

- **Bug: `WTF_CSRF_ENABLED=False` non disabilita il CSRF nei test e2e di `/login`**
  — `enforce_csrf_on_forms()` in `src/dashboard/app.py` chiama `csrf.protect()`
  direttamente nel `before_request`, che ignora il config `WTF_CSRF_ENABLED` (quel
  flag è rispettato solo dall'hook automatico di `CSRFProtect`, non da una chiamata
  manuale a `.protect()`). Il fixture `app` in `tests/conftest.py` imposta
  `WTF_CSRF_ENABLED: False` pensando di disattivarlo, ma non ha effetto sulle POST
  a `/login`. Risultato: 13 test in `tests/test_dashboard_app.py` falliscono con 400
  "CSRF token is missing" (tra cui `test_login_brute_force_returns_429_after_threshold`,
  marker `e2e`, escluso di default da `pytest.ini` → non viene mai eseguito in CI,
  quindi il bug è invisibile). Fix: nei test che non allegano un token CSRF esplicito,
  passare per `csrf.protect(apply_exemptions=True)` con vista esente, oppure far
  passare i test dal pattern già funzionante (fetch `/api/csrf-token` +
  header `X-CSRFToken`, vedi `test_login_breach_detection_after_repeated_failures`).
