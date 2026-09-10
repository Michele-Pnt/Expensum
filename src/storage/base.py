from abc import ABC, abstractmethod
from datetime import date


class FinancialStorage(ABC):
    """Interfaccia astratta per il layer di storage.
   
      Ogni backend (Notion, PostgreSQL, ecc.) deve implementare questi metodi.
      Il resto del codice (bot.py, main.py) usa solo questa interfaccia,
      senza sapere quale backend c'è sotto.
    """

    def close(self) -> None:
        """Rilascia le risorse del backend, se necessario.

        I backend senza risorse da rilasciare non devono implementare nulla.
        """
        return None

    @abstractmethod
    def get_category_names(self, include_archived: bool = False) -> list[str]:
        """Nomi delle categorie dell'utente, archiviate escluse per default.

        L'archiviazione è un concetto specifico del backend Postgres: i backend che
        non la supportano ignorano il parametro e restituiscono tutte le categorie.
        """
        ...

    @abstractmethod
    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: str,
        account_id: str,
        monthly_balance_id: str | None = None,
    ) -> dict:
        """Crea una nuova spesa e restituisce un dict con i dati salvati."""
        ...

    @abstractmethod
    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: str,
        income_category_id: int | None = None,
        income_category_name: str | None = None,
        income_type: str | None = None,
    ) -> dict:
        """Crea una nuova entrata e restituisce un dict con i dati salvati."""
        ...

    def get_income_categories(self, include_archived: bool = False) -> list[dict]:
        """Return the current user's income category DTOs.

        DTOs expose ``id``, ``name``, ``monthly_budget``, ``description``,
        ``description_summary``, ``average`` and ``archived``. Backends without
        category persistence return an empty list instead of leaking backend data.
        """
        return []

    def get_income_category_names(self, include_archived: bool = False) -> list[str]:
        """Return active income category names, excluding archived by default."""
        return [row["name"] for row in self.get_income_categories(include_archived)]

    def create_income_category(
        self, name: str, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict:
        """Create a user-owned income category."""
        raise NotImplementedError("Income categories are not supported by this backend")

    def update_income_category(self, category_id: int, **fields) -> dict | None:
        """Update a user-owned income category, or return None if it is not owned."""
        return None

    def delete_income_category(self, category_id: int) -> dict | None:
        """Delete an income category, preserving linked historical income rows."""
        raise NotImplementedError("Income categories are not supported by this backend")

    @abstractmethod
    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le spese nel periodo indicato.

        Ogni dict include `normalized_name`: la voce di spesa normalizzata (ancora del
        cluster su Postgres, fallback su `name` su Notion). È l'etichetta di
        raggruppamento: compare come titolo di gruppo nei grafici quando l'utente ha
        attivo "raggruppa" (vedi `/api/analytics/top-merchants`), ma non sostituisce
        mai `name` nelle liste di movimenti né nel dettaglio di una singola spesa —
        lì si mostra sempre la descrizione originale scritta dall'utente.

        Include anche `label_cluster_id` e `category_id` (entrambi `None` su Notion):
        servono alla UI per offrire la correzione manuale del raggruppamento
        ("Unisci"/"Dividi") partendo da una riga del grafico.
        """
        ...

    @abstractmethod
    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce i bilanci mensili nel periodo indicato."""
        ...

    @abstractmethod
    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutte le entrate nel periodo indicato."""
        ...

    @abstractmethod
    def fetch_accounts(self) -> list[dict]:
        """Restituisce tutti i conti dell'utente con il saldo."""
        ...

    @abstractmethod
    def create_account(self, name: str, initial_balance: float = 0.0) -> dict:
        """Crea un nuovo conto. Restituisce dict con almeno 'id' e 'name'."""
        ...

    @abstractmethod
    def create_category(
        self, name: str, monthly_budget: float | None = None,
        description: str | None = None, description_summary: str | None = None,
    ) -> dict:
        """Crea una nuova categoria. Restituisce dict con almeno 'id' e 'name'.

        `description`/`description_summary` sono supportati solo dal backend
        Postgres (usati dal parser LLM per contestualizzare la categorizzazione,
        vedi `ExpenseParser`); i backend che non li supportano (Notion) li ignorano.
        """
        ...

    @abstractmethod
    def create_transfer(
        self,
        transfer_date: date,
        amount: float,
        from_account_id: str,
        to_account_id: str,
        name: str | None = None,
    ) -> dict:
        """Crea un trasferimento tra due conti e restituisce un dict con i dati salvati."""
        ...

    @abstractmethod
    def fetch_transfers(self, start_date: date, end_date: date) -> list[dict]:
        """Restituisce tutti i trasferimenti nel periodo indicato."""
        ...

    def update_transfer(self, transfer_id: int, **kwargs) -> dict | None:
        """Aggiorna un trasferimento esistente. None se non trovato.

        Default no-op: i backend che non supportano l'update (es. Notion) ignorano
        silenziosamente la chiamata.
        """
        return None

    def delete_transfer(self, transfer_id: int) -> bool:
        """Elimina un trasferimento. Default no-op (backend non supportato)."""
        return False

    @abstractmethod
    def create_subscription(
        self,
        name: str,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        cadence: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        category_name: str | None = None,
    ) -> dict:
        """Crea un nuovo abbonamento. Restituisce dict con almeno 'id' e 'name'.

        `category_name` è l'alternativa backend-agnostica a `category_id`, per i
        chiamanti (es. `src/subscription_detector.py`) che non conoscono gli id
        interni del backend.
        """
        ...

    @abstractmethod
    def fetch_subscriptions(self) -> list[dict]:
        """Restituisce tutti gli abbonamenti dell'utente.

        Ogni dict contiene almeno: name, amount, last_billed (ISO string o None).
        """
        ...

    def update_subscription(self, sub_id: str, last_billed: date | None = None) -> bool:
        """Aggiorna i dati di un abbonamento. Per ora supportiamo solo last_billed."""
        return False

    def get_categories(self, include_archived: bool = False) -> list[dict]:
        """Restituisce id, nome, budget mensile e average di tutte le categorie.

        Implementazione di default: ritorna lista vuota. I backend che supportano
        questa funzionalità (PostgresStorage, NotionStorage) la sovrascrivono.
        """
        return []

    @abstractmethod
    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        """Ritorna l'ID del record Monthly Balance per il mese della data fornita.
        Se non esiste, lo crea.
        """
        ...

    def save_report(
        self,
        user_id: str,
        report_type: str,
        report_date: date,
        text_content: str,
        report_data: dict | None = None,
    ) -> str:
        """Salva un report generato e restituisce il share_token (UUID).

        Default no-op: backend che non supportano lo storico (es. Notion) ignorano
        silenziosamente la chiamata e restituiscono stringa vuota.
        """
        return ""

    def get_report_by_token(self, share_token: str) -> dict | None:
        """Recupera un report tramite share_token pubblico. None se non esiste."""
        return None

    def get_reports_for_user(self, user_id: str, limit: int = 24) -> list[dict]:
        """Lista report dell'utente, ordinati per data decrescente."""
        return []

    # ------------------------------------------------------------------ savings goals
    # Feature Pro, supportata solo da PostgresStorage. Default: non supportato,
    # cosi' NotionStorage non deve implementare nulla di questi metodi.

    def create_savings_goal(
        self,
        goal_type: str,
        name: str,
        target_amount: float,
        account_id: int | None = None,
        category_id: int | None = None,
        start_date: date | None = None,
        target_date: date | None = None,
    ) -> dict:
        """Crea un obiettivo di risparmio. Non supportato su Notion."""
        raise NotImplementedError("Gli obiettivi di risparmio richiedono il backend PostgreSQL")

    def fetch_savings_goals(self, status: str | None = None) -> list[dict]:
        """Restituisce gli obiettivi dell'utente, opzionalmente filtrati per stato."""
        return []

    def update_savings_goal(self, goal_id: int, **fields) -> dict | None:
        """Aggiorna un obiettivo esistente. None se non trovato."""
        return None

    def delete_savings_goal(self, goal_id: int) -> bool:
        """Elimina un obiettivo (e lo storico evaluation collegato)."""
        return False

    def save_savings_goal_evaluation(
        self,
        goal_id: int,
        period_month: date,
        progress_pct: float,
        score_label: str,
        eta_date: date | None,
    ) -> None:
        """Salva/aggiorna la valutazione mensile (voto + ETA) di un obiettivo."""
        return None

    def fetch_savings_goal_evaluations(self, goal_id: int, limit: int = 12) -> list[dict]:
        """Restituisce lo storico delle valutazioni mensili di un obiettivo."""
        return []

    # ------------------------------------------------------------------ loans
    # Feature Pro, supportata solo da PostgresStorage. Default: non supportato,
    # cosi' NotionStorage non deve implementare nulla di questi metodi.

    def create_loan(
        self,
        name: str,
        loan_type: str,
        principal_amount: float,
        disbursement_date: date,
        duration_months: int,
        rate_type: str,
        tan: float,
        taeg: float | None = None,
        spread: float | None = None,
        euribor_current: float | None = None,
        euribor_tenor: str | None = None,
        review_frequency: str | None = None,
        next_review_date: date | None = None,
        account_id: int | None = None,
        origination_fee: float | None = None,
        monthly_fee: float | None = None,
        payment_cadence: str = "monthly",
    ) -> dict:
        """Crea un mutuo/finanziamento. Non supportato su Notion."""
        raise NotImplementedError("Il tracking mutui/finanziamenti richiede il backend PostgreSQL")

    def fetch_loans(self, status: str | None = None) -> list[dict]:
        """Restituisce i loan dell'utente, opzionalmente filtrati per stato."""
        return []

    def update_loan(self, loan_id: int, **fields) -> dict | None:
        """Aggiorna un loan esistente (es. tasso variabile dopo una revisione). None se non trovato."""
        return None

    def delete_loan(self, loan_id: int) -> bool:
        """Elimina un loan (le spese già generate restano, con loan_id che punta a un id inesistente)."""
        return False

    def partially_repay_loan(self, loan_id: int, repayment_date: date, amount: float, mode: str) -> dict | None:
        """Registra un rimborso parziale del capitale."""
        return None

    def record_loan_monthly_charge(self, loan_id: int, period_month: date) -> dict | None:
        """Calcola e registra la spesa del mese corrente per un loan (idempotente su period_month).

        None se il loan non esiste, non è attivo, o il mese è già stato addebitato.
        """
        return None

    def fetch_loan_schedule(self, loan_id: int) -> list[dict]:
        """Piano di ammortamento completo del loan (per i grafici)."""
        return []

    # ------------------------------------------------------------------ mortgage simulations

    def create_mortgage_simulation(
        self, name: str, input_snapshot: dict, result_snapshot: dict,
    ) -> dict:
        """Salva una bozza di simulazione; richiede il backend PostgreSQL."""
        raise NotImplementedError("Le simulazioni mutuo richiedono il backend PostgreSQL")

    def fetch_mortgage_simulations(self) -> list[dict]:
        """Restituisce le bozze di simulazione dell'utente corrente."""
        return []

    def get_mortgage_simulation(self, simulation_id: int) -> dict | None:
        """Restituisce una bozza dell'utente corrente, se esiste."""
        return None

    def update_mortgage_simulation(
        self, simulation_id: int, name: str, input_snapshot: dict, result_snapshot: dict,
    ) -> dict | None:
        """Aggiorna una bozza dell'utente corrente, se esiste."""
        return None

    def duplicate_mortgage_simulation(self, simulation_id: int) -> dict | None:
        """Duplica una bozza dell'utente corrente, se esiste."""
        return None

    def convert_mortgage_simulation(self, simulation_id: int, loan_fields: dict) -> dict | None:
        """Converte una bozza attiva in un mutuo reale una sola volta."""
        return None

    def delete_mortgage_simulation(self, simulation_id: int) -> bool:
        """Elimina una bozza dell'utente corrente."""
        return False

    def apply_category_budgets(self, proposals: list[dict]) -> list[dict] | None:
        """Applica in modo atomico budget proposti per categorie dell'utente."""
        return None
