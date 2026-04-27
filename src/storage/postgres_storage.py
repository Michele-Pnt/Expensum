from datetime import date, datetime                                                                                                                          
                                                                                                                                                               
from sqlalchemy.orm import Session      
                                                                                                                                                            
from src.storage.base import FinancialStorage                                                                                                                
from src.storage.models import Account, UserCategory, Expense, Income, MonthlyBalance, Subscription
                                                                                                                                                            
                
class PostgresStorage(FinancialStorage):
    """Implementazione di FinancialStorage su PostgreSQL/SQLite via SQLAlchemy."""
                                            
    def __init__(self, session: Session, user_id: str) -> None:
        self._session = session         
        self._user_id = user_id                                                                                                                              
                                                                                                                                                            
    def get_category_names(self) -> list[str]:
        rows = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id
        ).all()
        return [r.name for r in rows]       
                                        
    def create_expense(
        self,
        expense_date: date,
        amount: float,
        name: str,
        category_name: str,
        account_id: str,
        monthly_balance_id: str | None = None,
    ) -> dict:
        # Risolvi Monthly Balance automaticamente se non fornito
        mb_id = monthly_balance_id or self.get_or_create_monthly_balance(expense_date)

        expense = Expense(
            user_id=self._user_id,
            expense_date=expense_date,
            amount=amount,
            name=name,
            category_name=category_name,
            account_id=account_id,
            monthly_balance_id=int(mb_id) if mb_id else None,
        )
        self._session.add(expense)

        # Aggiorna il saldo del conto: spesa → saldo scende
        if account_id:
            try:
                acc = self._session.query(Account).filter(
                    Account.id == int(account_id),
                    Account.user_id == self._user_id,
                ).first()
                if acc:
                    acc.balance = (acc.balance or 0.0) - amount
            except (ValueError, TypeError):
                pass  # account_id non numerico (es. Notion page_id)

        self._session.commit()
        return {
            "id": expense.id,
            "date": expense.expense_date,
            "amount": expense.amount,
            "name": expense.name,
            "category": expense.category_name,
            "account_id": expense.account_id,
        }

    def create_income(
        self,
        income_date: date,
        amount: float,
        name: str,
        account_id: str,
        income_type: str | None = None,
    ) -> dict:
        income = Income(
            user_id=self._user_id,
            income_date=income_date,
            amount=amount,
            name=name,
            account_id=account_id,
            income_type=income_type,
        )
        self._session.add(income)

        # Aggiorna il saldo del conto: entrata → saldo sale
        if account_id:
            try:
                acc = self._session.query(Account).filter(
                    Account.id == int(account_id),
                    Account.user_id == self._user_id,
                ).first()
                if acc:
                    acc.balance = (acc.balance or 0.0) + amount
            except (ValueError, TypeError):
                pass  # account_id non numerico

        self._session.commit()
        return {
            "id": income.id,
            "date": income.income_date,
            "amount": income.amount,
            "name": income.name,
            "account_id": income.account_id,
            "income_type": income.income_type,
        }                                   
                                        
    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        rows = self._session.query(Expense).filter(                                                                                                          
            Expense.user_id == self._user_id,
            Expense.expense_date >= start_date,                                                                                                              
            Expense.expense_date <= end_date,
        ).all()                                                                                                                                              
        return [
            {                                                                                                                                                
                "date": r.expense_date,
                "amount": r.amount,                                                                                                                          
                "name": r.name,
                "category": r.category_name,
                "account_id": r.account_id,
            }
            for r in rows                                                                                                                                    
        ]
                                                                                                                                                            
    def fetch_monthly_balances(self, start_date: date, end_date: date) -> list[dict]:
        rows = self._session.query(MonthlyBalance).filter(
            MonthlyBalance.user_id == self._user_id,
            MonthlyBalance.month >= start_date,                                                                                                              
            MonthlyBalance.month <= end_date,
        ).all()                                                                                                                                              
        return [
            {
                "month": r.month,
                "income_total": r.income_total,
                "expense_total": r.expense_total,
                "net_savings": r.net_savings,
            }                               
            for r in rows               
        ]
                                                                                                                                                            
    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        rows = self._session.query(Income).filter(                                                                                                           
            Income.user_id == self._user_id,
            Income.income_date >= start_date,
            Income.income_date <= end_date,
        ).all()                                                                                                                                              
        return [
            {
                "date": r.income_date,
                "amount": r.amount,
                "name": r.name,
                "account_id": r.account_id,
                "income_type": r.income_type,
            }
            for r in rows
        ]                               

    def fetch_accounts(self) -> list[dict]:
        rows = self._session.query(Account).filter(
            Account.user_id == self._user_id
        ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "balance": r.balance,
                "currency": r.currency,
                "account_type": r.account_type,
            }
            for r in rows
        ]

    def create_account(self, name: str, initial_balance: float = 0.0,
                       account_type: str | None = None) -> dict:
        account = Account(user_id=self._user_id, name=name, balance=initial_balance,
                          account_type=account_type)
        self._session.add(account)
        self._session.commit()
        return {"id": account.id, "name": account.name, "account_type": account.account_type}

    def create_category(self, name: str, monthly_budget: float | None = None) -> dict:
        category = UserCategory(user_id=self._user_id, name=name, monthly_budget=monthly_budget)
        self._session.add(category)
        self._session.commit()
        return {"id": category.id, "name": category.name, "monthly_budget": category.monthly_budget}

    def get_categories(self) -> list[dict]:
        """Restituisce id, nome e budget mensile di tutte le categorie dell'utente."""
        rows = self._session.query(UserCategory).filter(
            UserCategory.user_id == self._user_id
        ).all()
        return [{"id": r.id, "name": r.name, "monthly_budget": r.monthly_budget} for r in rows]

    def fetch_subscriptions(self) -> list[dict]:
        """Restituisce tutti gli abbonamenti dell'utente."""
        rows = self._session.query(Subscription).filter(
            Subscription.user_id == self._user_id
        ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "amount": r.amount,
                "last_billed": r.last_billed.isoformat() if r.last_billed else None,
                "sub_type": r.sub_type,
                "account_id": r.account_id,
                "category_id": r.category_id,
            }
            for r in rows
        ]

    def create_subscription(
        self,
        name: str,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
    ) -> dict:
        parsed_date = None
        if last_billed:
            from datetime import datetime as dt
            parsed_date = dt.strptime(last_billed, "%Y-%m-%d").date()
        subscription = Subscription(
            user_id=self._user_id,
            name=name,
            amount=amount,
            last_billed=parsed_date,
            sub_type=sub_type,
            account_id=account_id,
            category_id=category_id,
        )
        self._session.add(subscription)
        self._session.commit()
        return {
            "id": subscription.id,
            "name": subscription.name,
            "amount": subscription.amount,
            "last_billed": subscription.last_billed.isoformat() if subscription.last_billed else None,
            "sub_type": subscription.sub_type,
            "account_id": subscription.account_id,
            "category_id": subscription.category_id,
        }

    def delete_category(self, cat_id: int) -> bool:
        row = self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()
        if not row:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    def delete_account(self, account_id: int) -> bool:
        row = self._session.query(Account).filter(
            Account.id == account_id,
            Account.user_id == self._user_id,
        ).first()
        if not row:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    def delete_subscription(self, sub_id: int) -> bool:
        row = self._session.query(Subscription).filter(
            Subscription.id == sub_id,
            Subscription.user_id == self._user_id,
        ).first()
        if not row:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    def update_account(self, account_id: int, name: str | None = None,
                       balance: float | None = None,
                       account_type: str | None = None) -> dict | None:
        row = self._session.query(Account).filter(
            Account.id == account_id,
            Account.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if balance is not None:
            row.balance = balance
        if account_type is not None:
            row.account_type = account_type
        self._session.commit()
        return {"id": row.id, "name": row.name, "balance": row.balance, "account_type": row.account_type}

    def update_category(self, cat_id: int, name: str | None = None,
                        monthly_budget: float | None = None) -> dict | None:
        row = self._session.query(UserCategory).filter(
            UserCategory.id == cat_id,
            UserCategory.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if monthly_budget is not None:
            row.monthly_budget = monthly_budget
        self._session.commit()
        return {"id": row.id, "name": row.name, "monthly_budget": row.monthly_budget}

    def update_subscription(
        self,
        sub_id: int,
        name: str | None = None,
        amount: float | None = None,
        last_billed: str | None = None,
        sub_type: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
    ) -> dict | None:
        row = self._session.query(Subscription).filter(
            Subscription.id == sub_id,
            Subscription.user_id == self._user_id,
        ).first()
        if not row:
            return None
        if name is not None:
            row.name = name
        if amount is not None:
            row.amount = amount
        if last_billed is not None:
            from datetime import datetime as dt
            row.last_billed = dt.strptime(last_billed, "%Y-%m-%d").date()
        if sub_type is not None:
            row.sub_type = sub_type
        if account_id is not None:
            row.account_id = account_id
        if category_id is not None:
            row.category_id = category_id
        self._session.commit()
        return {
            "id": row.id,
            "name": row.name,
            "amount": row.amount,
            "last_billed": row.last_billed.isoformat() if row.last_billed else None,
            "sub_type": row.sub_type,
            "account_id": row.account_id,
            "category_id": row.category_id,
        }

    def get_or_create_monthly_balance(self, target_date: date) -> str | None:
        """Ritorna l'ID del record Monthly Balance per il mese della data fornita.
        Se non esiste, lo crea.
        """
        # Primo giorno del mese
        month_start = target_date.replace(day=1)
        
        row = self._session.query(MonthlyBalance).filter(
            MonthlyBalance.user_id == self._user_id,
            MonthlyBalance.month == month_start
        ).first()
        
        if row:
            return str(row.id)
            
        # Altrimenti crea
        new_mb = MonthlyBalance(
            user_id=self._user_id,
            month=month_start,
            income_total=0.0,
            expense_total=0.0,
            net_savings=0.0
        )
        self._session.add(new_mb)
        self._session.commit()
        return str(new_mb.id)