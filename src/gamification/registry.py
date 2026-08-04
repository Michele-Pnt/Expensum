"""Catalogo dichiarativo degli achievement.

Aggiungere un achievement significa aggiungere una riga a `ACHIEVEMENTS`: il motore
non va toccato. Le definizioni contengono solo dati (codici, soglie, XP, testi it/en,
slug di icona) e nessun markup: come vengono renderizzati lo decide la UI, che ancora
non esiste. Per la stessa ragione `icon` è uno slug e non un'emoji o un SVG.

REGOLA FERREA — `code` è contratto pubblico verso webapp e app mobile, oltre a essere
la chiave in `user_achievements`. Rinominarlo equivale a cancellare l'achievement per
tutti gli utenti che l'avevano sbloccato e crearne uno nuovo. Non si rinomina mai: si
deprecano e si aggiungono.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.gamification import metrics as M

# Famiglie: raggruppano gli achievement per la UI e permettono al motore di
# rivalutare solo il sottoinsieme rilevante a ogni evento.
FAMILY_VOLUME = "volume"
FAMILY_CHANNEL = "channel"
FAMILY_CATEGORIES = "categories"
FAMILY_REPORTS = "reports"
FAMILY_GOALS = "goals"
FAMILY_STREAK = "streak"
FAMILY_ONBOARDING = "onboarding"
#: Famiglia dei ritmi mensili: contiene sia gli achievement ciclici (ripetibili
#: ogni mese, per sempre) sia le milestone cumulative che ne contano i cicli.
FAMILY_CYCLES = "cycles"

#: Titoli delle famiglie, per l'API.
FAMILY_TITLES: dict[str, dict[str, str]] = {
    FAMILY_VOLUME: {"it": "Costanza", "en": "Consistency"},
    FAMILY_CYCLES: {"it": "Ritmo mensile", "en": "Monthly rhythm"},
    FAMILY_CHANNEL: {"it": "Adozione multicanale", "en": "Multi-channel adoption"},
    FAMILY_CATEGORIES: {"it": "Classificazione pulita", "en": "Clean classification"},
    FAMILY_REPORTS: {"it": "Report", "en": "Reports"},
    FAMILY_GOALS: {"it": "Obiettivi di risparmio", "en": "Savings goals"},
    FAMILY_STREAK: {"it": "Serie giornaliera", "en": "Daily streak"},
    FAMILY_ONBOARDING: {"it": "Primi passi", "en": "Getting started"},
}

ALL_BACKENDS = ("postgres", "notion")
ALL_PLANS = ("free", "pro")


@dataclass(frozen=True)
class AchievementDef:
    """Definizione immutabile di un achievement.

    Attributes:
        code: identificatore stabile. Contratto pubblico, non rinominabile.
        family: famiglia di appartenenza (una delle costanti FAMILY_*).
        tier: livello dentro la famiglia (1..N); 0 per gli achievement singoli.
        xp: esperienza concessa allo sblocco.
        icon: slug dell'icona; la UI decide come renderizzarlo.
        titles/descriptions: testi per lingua ('it' e 'en' sempre presenti).
        metric: metrica di riferimento; None per gli achievement sbloccati
            esplicitamente via `engine.award()`.
        threshold: valore della metrica da raggiungere.
        repeatable: se True può essere sbloccato più volte, distinto da `dedup_key`.
        hidden: non mostrato in catalogo finché non è sbloccato.
        supersedes: codice del tier precedente, così la UI può collassare la serie.
        backends/plans: dove l'achievement è ottenibile; altrove la famiglia viene
            esposta come "unavailable" invece di sparire, per poterla usare da teaser.
        order: ordinamento all'interno della famiglia.
    """

    code: str
    family: str
    xp: int
    icon: str
    titles: dict[str, str]
    descriptions: dict[str, str]
    tier: int = 0
    metric: str | None = None
    threshold: int = 1
    repeatable: bool = False
    hidden: bool = False
    supersedes: str | None = None
    backends: tuple[str, ...] = ALL_BACKENDS
    plans: tuple[str, ...] = ALL_PLANS
    order: int = 0

    def title(self, locale: str = "it") -> str:
        return self.titles.get(locale) or self.titles["it"]

    def description(self, locale: str = "it") -> str:
        return self.descriptions.get(locale) or self.descriptions["it"]

    def is_available(self, backend: str, plan_type: str) -> bool:
        """True se l'utente, con questo backend e piano, può ottenerlo."""
        return backend in self.backends and plan_type in self.plans


def _volume_tiers() -> list[AchievementDef]:
    """Milestone di volume: 25 spese, poi raddoppi. L'XP cresce meno del doppio."""
    # XP proporzionali al costo MARGINALE, con rendimento crescente: le soglie
    # raddoppiano, quindi anche il premio deve, altrimenti ogni tier vale meno del
    # precedente e chi è a 800 spese non ha motivo di arrivare a 1600.
    thresholds = (25, 50, 100, 200, 400, 800, 1600, 3200)
    xps = (15, 15, 35, 80, 170, 375, 810, 1700)
    titles_it = (
        "Si comincia", "Presa la mano", "Centometrista", "Doppio centinaio",
        "Quattrocento", "Ottocento", "Milleseicento", "Tremiladuecento",
    )
    titles_en = (
        "First steps", "Getting the hang of it", "Century", "Double century",
        "Four hundred", "Eight hundred", "Sixteen hundred", "Thirty-two hundred",
    )
    out = []
    for i, (threshold, xp) in enumerate(zip(thresholds, xps)):
        out.append(AchievementDef(
            code=f"volume_expenses_{threshold}",
            family=FAMILY_VOLUME,
            tier=i + 1,
            xp=xp,
            icon="receipt",
            titles={"it": titles_it[i], "en": titles_en[i]},
            descriptions={
                "it": f"Hai registrato {threshold} spese.",
                "en": f"You logged {threshold} expenses.",
            },
            metric=M.EXPENSES_TOTAL,
            threshold=threshold,
            supersedes=f"volume_expenses_{thresholds[i - 1]}" if i else None,
            order=i,
        ))
    return out


def _channel_tiers() -> list[AchievementDef]:
    """Un achievement per canale a 50 spese, più il grand slam su tutti e tre."""
    # Foto e voce sono funzioni Pro (bot.py blocca 'voice'/'photo' al piano free):
    # dichiararle disponibili a tutti mostrerebbe a un Free una barra di progresso
    # verso qualcosa che non potrà mai raggiungere.
    channels = (
        ("text", M.TX_TEXT, "keyboard", "Tastiera d'oro", "Golden keyboard",
         "scrivendo", "by typing", ALL_PLANS),
        ("photo", M.TX_PHOTO, "camera", "Occhio da scontrino", "Receipt eye",
         "fotografando gli scontrini", "from receipt photos", ("pro",)),
        ("voice", M.TX_VOICE, "mic", "A voce alta", "Out loud",
         "con messaggi vocali", "by voice", ("pro",)),
    )
    out = []
    for i, (slug, metric, icon, title_it, title_en, how_it, how_en, plans) in enumerate(channels):
        out.append(AchievementDef(
            code=f"channel_{slug}_50",
            family=FAMILY_CHANNEL,
            tier=1,
            xp=65,
            plans=plans,
            icon=icon,
            titles={"it": title_it, "en": title_en},
            descriptions={
                "it": f"Hai registrato 50 spese {how_it}.",
                "en": f"You logged 50 expenses {how_en}.",
            },
            metric=metric,
            threshold=50,
            order=i,
        ))
    out.append(AchievementDef(
        code="channel_grand_slam",
        family=FAMILY_CHANNEL,
        tier=2,
        xp=320,
        plans=("pro",),   # richiede foto e voce, entrambe Pro
        icon="trophy",
        titles={"it": "Grand Slam", "en": "Grand Slam"},
        descriptions={
            "it": "50 spese registrate in tutti e tre i modi: testo, scontrino e voce.",
            "en": "50 expenses logged each way: text, receipt and voice.",
        },
        metric=M.CHANNELS_MIN,
        threshold=50,
        order=3,
    ))
    return out


def _cycle_achievements() -> list[AchievementDef]:
    """Achievement CICLICI: si riguadagnano ogni mese, per sempre.

    Sono il motore di lungo periodo del sistema. Le famiglie a tier si esauriscono
    per costruzione — dodici mesi puliti finiscono al dodicesimo mese — e dopo di
    quello non resta nulla da sbloccare. I cicli non finiscono mai: rendono poco
    ma sempre, e tengono viva la progressione oltre il primo anno.

    Sono `repeatable` con `dedup_key` uguale al periodo (`YYYY-MM`), quindi lo
    unique constraint garantisce che uno stesso mese non venga premiato due volte
    anche se il job gira più volte o il backfill viene rieseguito.
    """
    return [
        AchievementDef(
            code="cycle_active_month",
            family=FAMILY_CYCLES,
            xp=20,
            icon="calendar",
            titles={"it": "Mese registrato", "en": "Month logged"},
            descriptions={
                "it": f"Hai registrato almeno {M.ACTIVE_MONTH_MIN_EXPENSES} spese in un mese.",
                "en": f"You logged at least {M.ACTIVE_MONTH_MIN_EXPENSES} expenses in a month.",
            },
            repeatable=True,
            order=0,
        ),
        AchievementDef(
            code="cycle_clean_month",
            family=FAMILY_CYCLES,
            xp=30,
            icon="sparkles",
            titles={"it": "Mese pulito", "en": "Clean month"},
            descriptions={
                "it": "Hai chiuso un mese senza nemmeno una spesa in «Altro».",
                "en": "You closed a month with no expense left in «Other».",
            },
            repeatable=True,
            backends=("postgres",),
            order=1,
        ),
        AchievementDef(
            code="cycle_report_month",
            family=FAMILY_CYCLES,
            xp=15,
            icon="book-open",
            titles={"it": "Report letto", "en": "Report read"},
            descriptions={
                "it": "Hai aperto almeno un report nel mese.",
                "en": "You opened at least one report during the month.",
            },
            repeatable=True,
            order=2,
        ),
    ]


def _clean_month_tiers() -> list[AchievementDef]:
    """Milestone sui mesi puliti totali. Solo Postgres.

    Contano i mesi puliti **cumulativi**, non consecutivi: un mese storto azzera
    la serie ma non cancella quelli già messi in cassa. È ciò che permette alle
    soglie di arrivare a tre anni senza diventare irraggiungibili — al contrario
    della serie consecutiva, che si rompe alla prima distrazione.
    """
    spec = [
        (3,  70,  "Trimestre in ordine",     "Tidy quarter"),
        (6,  130, "Semestre impeccabile",    "Flawless half-year"),
        (12, 260, "Un anno senza «Altro»",   "A year without «Other»"),
        (24, 480, "Due anni di ordine",      "Two tidy years"),
        (36, 700, "Tre anni senza «Altro»",  "Three years without «Other»"),
    ]
    out = []
    for i, (months, xp, it, en) in enumerate(spec):
        out.append(AchievementDef(
            code=f"clean_months_{months}",
            family=FAMILY_CATEGORIES,
            tier=i + 1,
            xp=xp,
            icon="sparkles",
            titles={"it": it, "en": en},
            descriptions={
                "it": f"{months} mesi chiusi senza spese finite in «Altro».",
                "en": f"{months} months closed with no expense left in «Other».",
            },
            metric=M.CLEAN_MONTHS_TOTAL,
            threshold=months,
            supersedes=f"clean_months_{spec[i - 1][0]}" if i else None,
            backends=("postgres",),
            order=i,
        ))
    return out


def _active_month_tiers() -> list[AchievementDef]:
    """Milestone sui mesi attivi: quanti mesi l'utente ha davvero usato il prodotto."""
    spec = [
        (3,  50,  "Tre mesi di seguito",  "Three months in"),
        (6,  110, "Mezzo anno",           "Half a year"),
        (12, 240, "Un anno con Expensum", "A year with Expensum"),
        (24, 460, "Due anni",             "Two years"),
        (36, 680, "Tre anni",             "Three years"),
    ]
    out = []
    for i, (months, xp, it, en) in enumerate(spec):
        out.append(AchievementDef(
            code=f"active_months_{months}",
            family=FAMILY_CYCLES,
            tier=i + 1,
            xp=xp,
            icon="calendar-check",
            titles={"it": it, "en": en},
            descriptions={
                "it": f"{months} mesi in cui hai tenuto i conti con Expensum.",
                "en": f"{months} months keeping your books with Expensum.",
            },
            metric=M.ACTIVE_MONTHS_TOTAL,
            threshold=months,
            supersedes=f"active_months_{spec[i - 1][0]}" if i else None,
            order=i + 10,
        ))
    return out


def _report_achievements() -> list[AchievementDef]:
    """Milestone sui report **aperti**, non su quelli generati.

    I report settimanali vengono prodotti automaticamente dal job del lunedì per
    ogni utente attivo: premiare la generazione significherebbe premiare il fatto
    di esistere. Resta un solo achievement sul generato, simbolico, per l'onboarding.
    """
    out = [
        AchievementDef(
            code="reports_first_generated",
            family=FAMILY_REPORTS,
            tier=1,
            xp=10,
            icon="file-text",
            titles={"it": "Primo report", "en": "First report"},
            descriptions={
                "it": "Il tuo primo report è pronto.",
                "en": "Your first report is ready.",
            },
            metric=M.REPORTS_GENERATED,
            threshold=1,
            order=0,
        ),
        AchievementDef(
            code="reports_first_opened",
            family=FAMILY_REPORTS,
            tier=1,
            xp=45,
            icon="book-open",
            titles={"it": "Letto davvero", "en": "Actually read"},
            descriptions={
                "it": "Hai aperto un report, non solo ricevuto.",
                "en": "You opened a report, not just received one.",
            },
            metric=M.REPORTS_OPENED,
            threshold=1,
            order=1,
        ),
    ]
    for i, (threshold, xp, title_it, title_en) in enumerate((
        (8, 140, "Otto letture", "Eight reads"),
        (24, 300, "Ventiquattro letture", "Twenty-four reads"),
        (52, 500, "Un anno di letture", "A year of reads"),
        (104, 780, "Due anni di letture", "Two years of reads"),
    )):
        out.append(AchievementDef(
            code=f"reports_opened_{threshold}",
            family=FAMILY_REPORTS,
            tier=i + 2,
            xp=xp,
            icon="file-stack",
            titles={"it": title_it, "en": title_en},
            descriptions={
                "it": f"Hai aperto {threshold} report.",
                "en": f"You opened {threshold} reports.",
            },
            metric=M.REPORTS_OPENED,
            threshold=threshold,
            supersedes="reports_first_opened" if i == 0 else None,
            order=i + 2,
        ))
    return out


def _goal_achievements() -> list[AchievementDef]:
    """Gli obiettivi sono Pro + Postgres: altrove la famiglia resta un teaser."""
    out = [AchievementDef(
        code="goal_reached",
        family=FAMILY_GOALS,
        xp=60,
        icon="target",
        titles={"it": "Obiettivo raggiunto", "en": "Goal reached"},
        descriptions={
            "it": "Hai portato a termine un obiettivo di risparmio.",
            "en": "You completed a savings goal.",
        },
        repeatable=True,
        backends=("postgres",),
        plans=("pro",),
        order=0,
    )]
    for i, (threshold, xp, title_it, title_en) in enumerate((
        (1, 55, "Primo traguardo", "First milestone"),
        (3, 125, "Tre obiettivi", "Three goals"),
        (5, 140, "Cinque obiettivi", "Five goals"),
        (10, 390, "Dieci obiettivi", "Ten goals"),
        (20, 700, "Venti obiettivi", "Twenty goals"),
    )):
        out.append(AchievementDef(
            code=f"goals_completed_{threshold}",
            family=FAMILY_GOALS,
            tier=i + 1,
            xp=xp,
            icon="flag",
            titles={"it": title_it, "en": title_en},
            descriptions={
                "it": (
                    "Hai raggiunto il tuo primo obiettivo di risparmio." if threshold == 1
                    else f"Hai raggiunto {threshold} obiettivi di risparmio."
                ),
                "en": (
                    "You reached your first savings goal." if threshold == 1
                    else f"You reached {threshold} savings goals."
                ),
            },
            metric=M.GOALS_COMPLETED,
            threshold=threshold,
            supersedes=f"goals_completed_{(1, 3, 5, 10, 20)[i - 1]}" if i else None,
            backends=("postgres",),
            plans=("pro",),
            order=i + 1,
        ))
    return out


def _streak_achievements() -> list[AchievementDef]:
    """Rispecchia i cicli streak già esistenti, senza duplicarne il reward Pro."""
    out = []
    # XP scontati rispetto allo sforzo: ogni ciclo concede già 14 giorni di Pro,
    # premiarlo a pieno significherebbe pagare due volte lo stesso comportamento.
    for i, (cycles, xp, title_it, title_en) in enumerate((
        (1, 10, "Primo ciclo", "First cycle"),
        (2, 50, "Due cicli", "Two cycles"),
        (3, 65, "Tre cicli", "Three cycles"),
        (5, 190, "Cinque cicli", "Five cycles"),
        (10, 645, "Dieci cicli", "Ten cycles"),
    )):
        out.append(AchievementDef(
            code=f"streak_cycle_{cycles}",
            family=FAMILY_STREAK,
            tier=i + 1,
            xp=xp,
            icon="flame",
            titles={"it": title_it, "en": title_en},
            descriptions={
                "it": (
                    "Hai completato il tuo primo ciclo di serie giornaliera." if cycles == 1
                    else f"Hai completato {cycles} cicli di serie giornaliera."
                ),
                "en": (
                    "You completed your first daily streak cycle." if cycles == 1
                    else f"You completed {cycles} daily streak cycles."
                ),
            },
            metric=M.STREAK_CYCLES,
            threshold=cycles,
            supersedes=f"streak_cycle_{(1, 2, 3, 5, 10)[i - 1]}" if i else None,
            order=i,
        ))
    for i, (days, xp) in enumerate(((14, 25), (28, 30), (42, 30), (56, 35))):
        out.append(AchievementDef(
            code=f"streak_days_{days}",
            family=FAMILY_STREAK,
            tier=i + 1,
            xp=xp,
            icon="calendar-check",
            titles={
                "it": f"{days} giorni di fila",
                "en": f"{days} days in a row",
            },
            descriptions={
                "it": f"Hai tenuto la serie per {days} giorni consecutivi.",
                "en": f"You kept the streak going for {days} consecutive days.",
            },
            metric=M.STREAK_MAX_DAYS,
            threshold=days,
            supersedes=f"streak_days_{(14, 28, 42, 56)[i - 1]}" if i else None,
            order=i + 5,
        ))
    return out


def _onboarding_achievements() -> list[AchievementDef]:
    return [
        AchievementDef(
            code="onboarding_telegram_linked",
            family=FAMILY_ONBOARDING,
            xp=30,
            icon="link",
            titles={"it": "Telegram collegato", "en": "Telegram connected"},
            descriptions={
                "it": "Hai collegato il bot Telegram al tuo account.",
                "en": "You connected the Telegram bot to your account.",
            },
            metric=M.TELEGRAM_LINKED,
            threshold=1,
            order=0,
        ),
        AchievementDef(
            code="onboarding_feedback_sent",
            family=FAMILY_ONBOARDING,
            xp=30,
            icon="message-circle",
            titles={"it": "Voce in capitolo", "en": "Your say"},
            descriptions={
                "it": "Ci hai mandato un feedback.",
                "en": "You sent us feedback.",
            },
            metric=M.FEEDBACK_SENT,
            threshold=1,
            order=1,
        ),
    ]


ACHIEVEMENTS: tuple[AchievementDef, ...] = tuple(
    _volume_tiers()
    + _cycle_achievements()
    + _active_month_tiers()
    + _channel_tiers()
    + _clean_month_tiers()
    + _report_achievements()
    + _goal_achievements()
    + _streak_achievements()
    + _onboarding_achievements()
)

#: Indici di accesso, costruiti una volta all'import.
BY_CODE: dict[str, AchievementDef] = {a.code: a for a in ACHIEVEMENTS}

BY_FAMILY: dict[str, tuple[AchievementDef, ...]] = {
    family: tuple(sorted(
        (a for a in ACHIEVEMENTS if a.family == family),
        key=lambda a: (a.order, a.threshold),
    ))
    for family in FAMILY_TITLES
}

#: Achievement per metrica, ordinati per soglia crescente: il motore li scorre in
#: ordine e può sbloccarne più di uno nella stessa passata.
BY_METRIC: dict[str, tuple[AchievementDef, ...]] = {}
for _a in ACHIEVEMENTS:
    if _a.metric:
        BY_METRIC.setdefault(_a.metric, [])  # type: ignore[arg-type]
        BY_METRIC[_a.metric].append(_a)      # type: ignore[union-attr]
BY_METRIC = {
    metric: tuple(sorted(defs, key=lambda a: a.threshold))
    for metric, defs in BY_METRIC.items()
}

#: Famiglie toccate da ciascuna metrica, per rivalutare solo il necessario.
FAMILIES_BY_METRIC: dict[str, tuple[str, ...]] = {
    metric: tuple(sorted({a.family for a in defs}))
    for metric, defs in BY_METRIC.items()
}


def family_title(family: str, locale: str = "it") -> str:
    titles = FAMILY_TITLES.get(family, {})
    return titles.get(locale) or titles.get("it") or family
