from src.user_store import UserStore
from config import Config

store = UserStore(Config.DATABASE_URL)
try:
    with store.Session() as s:
        from src.user_store import User
        user = s.query(User).first()
        if user:
            print("Consuming tokens for", user.chat_id)
            res = store.consume_tokens(user.chat_id, 100)
            print("Result:", res)
            
            from src.user_store import LlmUsageEvent
            events = s.query(LlmUsageEvent).filter_by(chat_id=user.chat_id).count()
            print("Total events:", events)
        else:
            print("No users")
except Exception as e:
    import traceback
    traceback.print_exc()
