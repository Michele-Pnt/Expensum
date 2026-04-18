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
    ) -> dict:
        expense = Expense(                                                                                                                                   
            user_id=self._user_id,      
            expense_date=expense_date,
            amount=amount,                                                                                                                                   
            name=name,
            category_name=category_name,                                                                                                                     
            account_id=account_id,          
        )                               
        self._session.add(expense)
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
            }
            for r in rows
        ]

    def create_account(self, name: str, initial_balance: float = 0.0) -> dict:
        account = Account(user_id=self._user_id, name=name, balance=initial_balance)
        self._session.add(account)
        self._session.commit()
        return {"id": account.id, "name": account.name}

    def create_category(self, name: str) -> dict:
        category = UserCategory(user_id=self._user_id, name=name)
        self._session.add(category)
        self._session.commit()
        return {"id": category.id, "name": category.name}

    def create_subscription(self, name: str) -> dict:
        subscription = Subscription(user_id=self._user_id, name=name)
        self._session.add(subscription)
        self._session.commit()
        return {"id": subscription.id, "name": subscription.name}