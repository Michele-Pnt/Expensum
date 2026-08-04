"""
src/workspace_bootstrapper.py — Inizializzazione automatica del workspace utente.

Viene chiamato una sola volta al termine dell'OAuth, dopo che i 7 database
Notion sono stati scoperti e salvati. Crea dati di default (categorie, conti,
abbonamenti) se il workspace è ancora vuoto.

Idempotente: se il workspace è già popolato non crea duplicati.
"""

import logging
from typing import NamedTuple

from src.storage.base import FinancialStorage

logger = logging.getLogger("financial_agent.bootstrapper")

# ---------------------------------------------------------------------------
# Dati di default
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: list[str] = [
    # Abitazione (35% budget medio ISTAT 2024)
    "Affitto",
    "Mutuo",
    "Bollette luce",
    "Bollette gas",
    "Acqua",
    "Condominio",
    "Casa Vario",
    # Alimentari (19% budget ISTAT 2024)
    "Supermercato",
    "Mercato",
    # Ristorazione (6% budget, +4% YoY ISTAT 2024)
    "Ristorante",
    "Bar",
    "Food delivery",
    # Trasporti (11% budget ISTAT 2024)
    "Carburante",
    "Mezzi pubblici",
    "Taxi",
    "Parcheggio",
    "Auto Vario",
    # Salute
    "Farmacia",
    "Medicina",
    # Comunicazione
    "Telefono",
    "Internet",
    # Persona
    "Abbigliamento",
    "Scarpe",
    "Parrucchiere",
    "Igiene personale",
    # Finanza
    "Assicurazioni",
    "Banca",
    # Varie
    "Regali",
    "Altro",
]

# Categorie aggiuntive per tag stile di vita selezionati in onboarding.
# Nessuna di queste duplica voci già presenti in DEFAULT_CATEGORIES.
HOBBY_CATEGORIES: dict[str, list[str]] = {
    # 💪 Sport / Palestra
    "palestra": [
        "Palestra",
        "Abbigliamento sportivo",
        "Integratori",
        "Attrezzatura sportiva",
    ],
    # 📺 Streaming / Gaming
    "streaming": [
        "Gaming",
        "Abbonamenti digitali",
        "E-book",
    ],
    # ✈️ Viaggi
    "viaggi": [
        "Voli",
        "Alloggio",
        "Noleggio auto",
        "Escursioni",
        "Visti e documenti",
        "Assicurazione viaggio",
        "Souvenir",
    ],
    # 🎭 Cinema / Cultura
    "cultura": [
        "Cinema",
        "Teatro",
        "Concerti",
        "Musei",
        "Libri",
        "Riviste e podcast",
    ],
    # 💻 Tech / Elettronica
    "tech": [
        "Smartphone",
        "PC e laptop",
        "Accessori tech",
        "Riparazioni tech",
        "Domotica",
    ],
    # 🐾 Animali domestici
    "animali": [
        "Veterinario",
        "Cibo animali",
        "Farmaci animali",
        "Toelettatura",
        "Accessori animali",
        "Pensione animali",
        "Assicurazione animali",
    ],
    # 🍳 Cibo / Gourmet
    "cucina": [
        "Alcolici",
        "Attrezzatura cucina",
        "Corsi di cucina",
    ],
    # 👶 Famiglia / Figli
    "famiglia": [
        "Scuola",
        "Asilo nido",
        "Rette universitarie",
        "Doposcuola",
        "Sport figli",
        "Giocattoli",
        "Abbigliamento bambini",
        "Babysitter",
        "Gite scolastiche",
        "Pediatra",
    ],
    # 👗 Moda / Beauty
    "moda": [
        "Borse e accessori",
        "Estetista",
        "Profumi",
        "Cosmetici",
        "Scarpe"
    ],
}


# Descrizioni comportamentali statiche per DEFAULT_CATEGORIES + HOBBY_CATEGORIES,
# usate come `description_summary` nel prompt del parser LLM (vedi
# `ExpenseParser(category_descriptions=...)`) — nessuna chiamata LLM necessaria,
# stesso principio di `categories_from_hobbies`: lookup statica invece di un
# giro AI per un elenco finito e conosciuto in anticipo. L'utente può comunque
# riscriverle in webapp in qualsiasi momento (sovrascrivono queste).
CATEGORY_DESCRIPTIONS: dict[str, str] = {
    # Abitazione
    "Affitto": "Il canone di affitto mensile della casa",
    "Mutuo": "La rata mensile del mutuo sulla casa",
    "Bollette luce": "Spese per la fornitura di energia elettrica di casa",
    "Bollette gas": "Spese per la fornitura di gas di casa",
    "Acqua": "Spese per la fornitura idrica di casa",
    "Condominio": "Spese condominiali della casa",
    "Casa Vario": "Piccole spese di manutenzione o arredamento della casa",
    # Alimentari
    "Supermercato": "Spesa alimentare fatta al supermercato",
    "Mercato": "Spesa alimentare fatta al mercato rionale",
    # Ristorazione
    "Ristorante": "Spese per mangiare fuori al ristorante",
    "Bar": "Spese al bar per caffè, colazioni o aperitivi veloci",
    "Food delivery": "Cibo ordinato a domicilio tramite app di delivery",
    # Trasporti
    "Carburante": "Spese per il rifornimento di benzina o diesel dell'auto",
    "Mezzi pubblici": "Biglietti e abbonamenti per bus, treno o metro",
    "Taxi": "Corse in taxi o servizi tipo Uber",
    "Parcheggio": "Spese per parcheggi e soste auto",
    "Auto Vario": "Manutenzione, revisione, bollo e altre spese generiche dell'auto",
    # Salute
    "Farmacia": "Acquisti in farmacia (medicinali da banco, prodotti sanitari)",
    "Medicina": "Visite mediche, esami e cure sanitarie",
    # Comunicazione
    "Telefono": "Abbonamento telefonico o ricariche del cellulare",
    "Internet": "Abbonamento internet/fibra di casa",
    # Persona
    "Abbigliamento": "Acquisto di vestiti",
    "Scarpe": "Acquisto di scarpe",
    "Parrucchiere": "Spese dal parrucchiere o barbiere",
    "Igiene personale": "Prodotti per l'igiene personale quotidiana",
    # Finanza
    "Assicurazioni": "Polizze assicurative (esclusa auto e viaggio, vedi categorie dedicate)",
    "Banca": "Commissioni e costi bancari",
    # Varie
    "Regali": "Regali fatti ad altre persone",
    "Altro": "Spese generiche che non rientrano in nessun'altra categoria",

    # Hobby — palestra
    "Palestra": "Abbonamento o ingressi in palestra",
    "Abbigliamento sportivo": "Vestiti e scarpe per fare sport",
    "Integratori": "Integratori alimentari e proteine per l'allenamento",
    "Attrezzatura sportiva": "Attrezzi e accessori per l'attività sportiva",
    # Hobby — streaming/gaming
    "Gaming": "Videogiochi, contenuti e abbonamenti gaming",
    "Abbonamenti digitali": "Abbonamenti a servizi di streaming video o musica",
    "E-book": "Acquisto di libri digitali",
    # Hobby — viaggi
    "Voli": "Biglietti aerei per viaggi",
    "Alloggio": "Hotel, B&B o affitti brevi durante un viaggio",
    "Noleggio auto": "Noleggio di un'auto durante un viaggio",
    "Escursioni": "Attività ed escursioni fatte durante un viaggio",
    "Visti e documenti": "Visti, passaporti e documenti necessari per viaggiare",
    "Assicurazione viaggio": "Polizza assicurativa per un viaggio",
    "Souvenir": "Souvenir e ricordi acquistati durante un viaggio",
    # Hobby — cultura
    "Cinema": "Biglietti del cinema",
    "Teatro": "Biglietti a spettacoli teatrali",
    "Concerti": "Biglietti per concerti ed eventi musicali dal vivo",
    "Musei": "Ingressi a musei e mostre",
    "Libri": "Acquisto di libri cartacei",
    "Riviste e podcast": "Abbonamenti a riviste o contenuti podcast a pagamento",
    # Hobby — tech
    "Smartphone": "Acquisto o riparazione di uno smartphone",
    "PC e laptop": "Acquisto o riparazione di un computer",
    "Accessori tech": "Accessori elettronici (cuffie, caricabatterie, cavi, ecc.)",
    "Riparazioni tech": "Riparazioni di dispositivi elettronici",
    "Domotica": "Dispositivi smart home e domotica",
    # Hobby — animali
    "Veterinario": "Visite veterinarie per l'animale domestico",
    "Cibo animali": "Cibo per l'animale domestico",
    "Farmaci animali": "Farmaci e cure per l'animale domestico",
    "Toelettatura": "Toelettatura dell'animale domestico",
    "Accessori animali": "Accessori per l'animale domestico (guinzagli, cucce, giochi)",
    "Pensione animali": "Pensione o dog-sitting per l'animale domestico",
    "Assicurazione animali": "Polizza assicurativa per l'animale domestico",
    # Hobby — cucina
    "Alcolici": "Acquisto di vino, birra o alcolici",
    "Attrezzatura cucina": "Utensili ed elettrodomestici da cucina",
    "Corsi di cucina": "Corsi di cucina",
    # Hobby — famiglia
    "Scuola": "Rette e materiale scolastico dei figli",
    "Asilo nido": "Retta dell'asilo nido",
    "Rette universitarie": "Tasse e rette universitarie",
    "Doposcuola": "Attività di doposcuola dei figli",
    "Sport figli": "Attività sportive dei figli",
    "Giocattoli": "Giocattoli per i figli",
    "Abbigliamento bambini": "Vestiti per i figli",
    "Babysitter": "Servizio di babysitter",
    "Gite scolastiche": "Gite scolastiche dei figli",
    "Pediatra": "Visite pediatriche dei figli",
    # Hobby — moda
    "Borse e accessori": "Borse e accessori moda",
    "Estetista": "Trattamenti estetici",
    "Profumi": "Acquisto di profumi",
    "Cosmetici": "Acquisto di cosmetici e make-up",
}


def categories_from_hobbies(hobbies: list[str]) -> list[str]:
    """Ritorna categorie deduplicate: DEFAULT_CATEGORIES + extra da hobby selezionati.

    Usata nell'onboarding al posto della chiamata AI — lookup statica basata su
    dati ISTAT 2024 sulle abitudini finanziarie degli italiani 18-50 anni.
    """
    seen: set[str] = set()
    result: list[str] = []
    for cat in DEFAULT_CATEGORIES:
        if cat not in seen:
            seen.add(cat)
            result.append(cat)
    for tag in hobbies:
        for cat in HOBBY_CATEGORIES.get(tag, []):
            if cat not in seen:
                seen.add(cat)
                result.append(cat)
    return result

DEFAULT_ACCOUNTS: list[tuple[str, float]] = []

# Abbonamenti di default vuoti — l'utente li aggiunge nel setup
DEFAULT_SUBSCRIPTIONS: list[str] = []


# ---------------------------------------------------------------------------
# Risultato del bootstrap
# ---------------------------------------------------------------------------

class BootstrapResult(NamedTuple):
    categories_created: list[str]
    accounts_created: list[str]
    subscriptions_created: list[str]
    skipped_categories: bool
    skipped_accounts: bool

    def is_empty(self) -> bool:
        """True se non è stato creato nulla (workspace già popolato)."""
        return (
            not self.categories_created
            and not self.accounts_created
            and not self.subscriptions_created
        )

    def to_telegram_message(self) -> str:
        """Genera il riepilogo da inviare all'utente via Telegram."""
        if self.is_empty():
            return ""

        lines = ["🚀 <b>Workspace inizializzato!</b>\n"]

        if self.categories_created:
            lines.append(
                f"📂 <b>Categorie create ({len(self.categories_created)}):</b>\n"
                "Abbiamo impostato per te delle categorie standard, pronte all'uso. "
                "Puoi modificarle, rimuoverle o aggiungerne di nuove in qualsiasi momento "
                "usando il pulsante qui sotto."
            )
        elif self.skipped_categories:
            lines.append("📂 Categorie: già presenti, nessuna modifica.")

        if self.accounts_created:
            lines.append(f"\n🏦 <b>Conti creati ({len(self.accounts_created)}):</b>")
            lines.append(", ".join(self.accounts_created))
        elif self.skipped_accounts:
            lines.append("\n🏦 Conti: già presenti, nessuna modifica.")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_workspace(storage: FinancialStorage) -> BootstrapResult:
    """Inizializza il workspace con dati di default.

    Controlla prima se il workspace è già popolato per garantire idempotenza:
    - Se esistono categorie → non ne crea di nuove
    - Se esistono conti → non ne crea di nuovi

    Args:
        storage: implementazione di FinancialStorage dell'utente

    Returns:
        BootstrapResult con il dettaglio di ciò che è stato creato
    """
    categories_created: list[str] = []
    accounts_created: list[str] = []
    subscriptions_created: list[str] = []
    skipped_categories = False
    skipped_accounts = False

    # --- Categorie ---
    try:
        existing_categories = storage.get_category_names(include_archived=True)
        if existing_categories:
            logger.info(
                "[Bootstrap] Categorie già presenti (%d), skip.", len(existing_categories)
            )
            skipped_categories = True
        else:
            for name in DEFAULT_CATEGORIES:
                storage.create_category(name, description_summary=CATEGORY_DESCRIPTIONS.get(name))
                categories_created.append(name)
                logger.info("[Bootstrap] Categoria creata: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione categorie: %s", e)

    # --- Conti ---
    try:
        existing_accounts = storage.fetch_accounts()
        if existing_accounts:
            logger.info(
                "[Bootstrap] Conti già presenti (%d), skip.", len(existing_accounts)
            )
            skipped_accounts = True
        else:
            for name, balance in DEFAULT_ACCOUNTS:
                storage.create_account(name, initial_balance=balance)
                accounts_created.append(name)
                logger.info("[Bootstrap] Conto creato: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione conti: %s", e)

    # --- Abbonamenti ---
    # Default vuoti: vengono creati solo se DEFAULT_SUBSCRIPTIONS è popolato
    try:
        for name in DEFAULT_SUBSCRIPTIONS:
            storage.create_subscription(name)
            subscriptions_created.append(name)
            logger.info("[Bootstrap] Abbonamento creato: %s", name)
    except Exception as e:
        logger.error("[Bootstrap] Errore creazione abbonamenti: %s", e)

    result = BootstrapResult(
        categories_created=categories_created,
        accounts_created=accounts_created,
        subscriptions_created=subscriptions_created,
        skipped_categories=skipped_categories,
        skipped_accounts=skipped_accounts,
    )
    logger.info(
        "[Bootstrap] Completato — categorie: %d, conti: %d, abbonamenti: %d",
        len(categories_created),
        len(accounts_created),
        len(subscriptions_created),
    )
    return result


def bootstrap_lifestyle_categories(
    storage: FinancialStorage,
    selected_categories: list[str],
) -> list[str]:
    """Crea le categorie selezionate dall'utente nel wizard di onboarding.

    Idempotente: verifica le categorie esistenti prima di creare per evitare duplicati.

    Args:
        storage: implementazione di FinancialStorage dell'utente
        selected_categories: lista di nomi categoria approvati dall'utente

    Returns:
        Lista dei nomi effettivamente creati (esclusi i duplicati già esistenti)
    """
    created: list[str] = []
    try:
        existing = {name.lower() for name in storage.get_category_names(include_archived=True)}
        for name in selected_categories:
            if name.lower() not in existing:
                storage.create_category(name, description_summary=CATEGORY_DESCRIPTIONS.get(name))
                created.append(name)
                existing.add(name.lower())
                logger.info("[Bootstrap lifestyle] Categoria creata: %s", name)
    except Exception as e:
        logger.error("[Bootstrap lifestyle] Errore creazione categorie: %s", e)
    logger.info("[Bootstrap lifestyle] Completato — categorie create: %d", len(created))
    return created
