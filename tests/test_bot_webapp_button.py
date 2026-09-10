"""Test per `_webapp_button` (bot.py) — bottone link verso `/login?next=<path>`.

Tutti i link generati dal bot devono aprirsi nel browser predefinito del
dispositivo, mai nel WebView/mini-app interno di Telegram: il bottone è sempre
`url=`, mai `web_app=WebAppInfo(...)`. `/login?next=<path>` autentica via
sessione browser e poi redirige alla pagina target (stesso pattern dei link
nelle email di lifecycle trial, vedi `_safe_next_url` in `src/dashboard/app.py`).
"""
import pytest

pytestmark = pytest.mark.unit


def test_webapp_button_is_plain_url_button(monkeypatch):
    import bot
    monkeypatch.setattr(bot.Config, "WEBAPP_BASE_URL", "https://app.expensum.it")

    result = bot._webapp_button("📊 Apri", "/dashboard")

    button = result.inline_keyboard[0][0]
    assert button.text == "📊 Apri"
    assert button.web_app is None
    assert button.url == "https://app.expensum.it/login?next=%2Fdashboard"


def test_webapp_button_works_with_http_url(monkeypatch):
    """A differenza dei bottoni `web_app`, Telegram accetta `url` anche non-https:
    niente guardia/degrado necessario per lo sviluppo locale (WEBAPP_BASE_URL=http://localhost)."""
    import bot
    monkeypatch.setattr(bot.Config, "WEBAPP_BASE_URL", "http://localhost:3000")

    result = bot._webapp_button("📊 Apri", "/dashboard")

    button = result.inline_keyboard[0][0]
    assert button.url == "http://localhost:3000/login?next=%2Fdashboard"


def test_webapp_button_encodes_query_string_in_path():
    """Un path con la propria query string (es. il tour post-onboarding) va incapsulato
    per intero nel valore di `next`, non interpretato come query string di /login."""
    import bot

    result = bot._webapp_button("✨ Scopri Expensum", "/chat?tour=1&demo=1")

    button = result.inline_keyboard[0][0]
    assert "next=%2Fchat%3Ftour%3D1%26demo%3D1" in button.url
