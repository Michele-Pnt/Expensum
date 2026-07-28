"""
scripts/add_two_accounts_demo_user.py — Aggiunge 2 conti extra (Carta di Credito,
Investimenti) all'utente demo gia' esistente (demo_local_test_user), con qualche
movimento minimo per non lasciarli completamente vuoti.

Non rigenera l'utente: presuppone che scripts/seed_demo_user_local.py sia gia'
stato eseguito. Va lanciato SOLO contro il DB locale.
"""
import random
from datetime import date

from src.user_store import UserStore
from src.storage.postgres_storage import PostgresStorage
import config

CHAT_ID = "demo_local_test_user"


def main() -> None:
    if "localhost" not in config.Config.DATABASE_URL and "127.0.0.1" not in config.Config.DATABASE_URL:
        raise SystemExit("Questo script va eseguito SOLO contro il container di sviluppo locale.")

    random.seed(11)
    store = UserStore(db_url=config.Config.DATABASE_URL)
    today = date.today()

    with store.Session() as session:
        storage = PostgresStorage(session=session, user_id=CHAT_ID)

        credit_card = storage.create_account("Carta di Credito", initial_balance=0.0, account_type="Carta di credito")
        investments = storage.create_account("Investimenti", initial_balance=2000.0, account_type="Investimento")

        # Qualche movimento realistico sulla carta di credito (ultimi 3 mesi)
        for i in range(3):
            month_ago = today.month - i
            year = today.year
            while month_ago <= 0:
                month_ago += 12
                year -= 1
            spend_date = date(year, month_ago, 20)
            if spend_date > today:
                continue
            storage.create_expense(
                expense_date=spend_date,
                amount=round(random.uniform(40, 150), 2),
                name="Spesa online",
                category_name="Shopping",
                account_id=credit_card["id"],
            )

        # Un paio di versamenti sul conto investimenti
        for i in range(2):
            month_ago = today.month - (i * 3 + 2)
            year = today.year
            while month_ago <= 0:
                month_ago += 12
                year -= 1
            d = date(year, month_ago, 5)
            if d > today:
                continue
            storage.create_income(
                income_date=d,
                amount=round(random.uniform(300, 600), 2),
                name="Versamento investimento",
                account_id=investments["id"],
                income_type="investimento",
            )

    print("Conti aggiunti con successo:")
    print(f"  - Carta di Credito (id={credit_card['id']})")
    print(f"  - Investimenti (id={investments['id']})")


if __name__ == "__main__":
    main()
