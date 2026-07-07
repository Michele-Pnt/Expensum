import sys
import os

# Aggiunge la root del progetto al path per importare src
sys.path.append(os.getcwd())

try:
    from src.user_store import UserStore, User, DailyMetrics, Feedback, OAuthSession
except ImportError as e:
    print(f"Errore di importazione: {e}")
    sys.exit(1)

def clear_data():
    # Inizializza lo store (usa di default sqlite:///users.db)
    store = UserStore()
    
    with store.Session() as session:
        print("--- Inizio pulizia database utenti ---")
        
        try:
            # Eliminiamo in ordine per rispettare i vincoli di foreign key
            num_feedbacks = session.query(Feedback).delete()
            print(f"Feedback eliminati: {num_feedbacks}")
            
            num_usage = session.query(DailyMetrics).delete()
            print(f"Log di utilizzo eliminati: {num_usage}")
            
            num_sessions = session.query(OAuthSession).delete()
            print(f"Sessioni OAuth eliminate: {num_sessions}")
            
            num_users = session.query(User).delete()
            print(f"Utenti eliminati: {num_users}")
            
            session.commit()
            print("--- Pulizia completata con successo ---")
        except Exception as e:
            session.rollback()
            print(f"Errore durante la pulizia: {e}")
            sys.exit(1)

if __name__ == "__main__":
    clear_data()
