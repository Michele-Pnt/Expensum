"""Metriche di gamification: le grandezze su cui si misurano gli achievement.

Sono nomi di chiave in `user_metric_counters`, quindi **contratto di persistenza**:
rinominare una costante equivale a perdere il contatore di tutti gli utenti. I
valori nuovi si aggiungono, quelli esistenti non si toccano.

Tutte le metriche sono conteggi di *utilizzo* del prodotto, mai di risultati
finanziari: non esistono achievement su "quanto hai risparmiato", perché senza una
sincronizzazione bancaria verificabile sarebbero premi su dati auto-dichiarati.
"""

from __future__ import annotations

# Volume complessivo di spese confermate.
EXPENSES_TOTAL = "expenses_total"

# Spese confermate per canale di inserimento (adozione multicanale).
TX_TEXT = "tx_text"
TX_PHOTO = "tx_photo"
TX_VOICE = "tx_voice"

# Report generati e aperti (tracciati server-side in `report_events`).
REPORTS_GENERATED = "reports_generated"
REPORTS_OPENED = "reports_opened"

# Mesi solari consecutivi chiusi senza nemmeno una spesa nella categoria di
# fallback: misura quanto l'utente tiene pulita la propria classificazione.
CLEAN_MONTHS_STREAK = "clean_months_streak"

# ---------------------------------------------------------------------------
# Contatori dei cicli mensili
#
# Reggono le milestone cumulative, che a differenza delle serie consecutive non
# regrediscono mai: un mese storto azzera la serie ma non cancella i mesi buoni
# già messi in cassa. Servono a dare all'utente un asse che non si esaurisce.
# ---------------------------------------------------------------------------

#: Mesi (non necessariamente consecutivi) chiusi senza spese nella categoria fallback.
CLEAN_MONTHS_TOTAL = "clean_months_total"

#: Mesi in cui l'utente ha registrato almeno `ACTIVE_MONTH_MIN_EXPENSES` spese.
ACTIVE_MONTHS_TOTAL = "active_months_total"

#: Mesi in cui l'utente ha aperto almeno un report.
REPORT_MONTHS_TOTAL = "report_months_total"

# Obiettivi di risparmio portati a termine.
GOALS_COMPLETED = "goals_completed"

# Streak: cicli completati e giorno più alto mai raggiunto.
STREAK_CYCLES = "streak_cycles_completed"
STREAK_MAX_DAYS = "streak_max_days"

# Attivazione: flag 0/1.
TELEGRAM_LINKED = "telegram_linked"
FEEDBACK_SENT = "feedback_sent"

# Metrica derivata (calcolata, mai persistita): il canale meno usato fra i tre.
# È ciò che rende esprimibile il "grand slam" — 50 spese su *tutti* i canali —
# come una normale soglia, senza casi speciali nel motore.
CHANNELS_MIN = "channels_min"

#: Spese minime perché un mese conti come "attivo". Sotto questa soglia il mese
#: non è né attivo né valutabile come pulito: senza una soglia basterebbe non
#: registrare nulla per collezionare mesi puliti a vuoto.
ACTIVE_MONTH_MIN_EXPENSES = 5

#: Tutte le metriche persistite (le derivate non compaiono).
ALL_METRICS: tuple[str, ...] = (
    EXPENSES_TOTAL,
    TX_TEXT, TX_PHOTO, TX_VOICE,
    REPORTS_GENERATED, REPORTS_OPENED,
    CLEAN_MONTHS_STREAK,
    CLEAN_MONTHS_TOTAL, ACTIVE_MONTHS_TOTAL, REPORT_MONTHS_TOTAL,
    GOALS_COMPLETED,
    STREAK_CYCLES, STREAK_MAX_DAYS,
    TELEGRAM_LINKED, FEEDBACK_SENT,
)

#: Metrica associata a ciascun canale di inserimento di `TxEvent.input_method`.
#: `button` non compare: è la conferma di una spesa già inserita in un altro modo.
INPUT_METHOD_METRICS: dict[str, str] = {
    "text": TX_TEXT,
    "photo": TX_PHOTO,
    "voice": TX_VOICE,
}


def derived_metrics(counters: dict[str, int]) -> dict[str, int]:
    """Metriche calcolate al volo a partire da quelle persistite."""
    return {
        CHANNELS_MIN: min(
            counters.get(TX_TEXT, 0),
            counters.get(TX_PHOTO, 0),
            counters.get(TX_VOICE, 0),
        ),
    }


def with_derived(counters: dict[str, int]) -> dict[str, int]:
    """I contatori dell'utente più le metriche derivate, pronti per la valutazione."""
    return {**counters, **derived_metrics(counters)}
