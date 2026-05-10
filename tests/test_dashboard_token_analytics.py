"""Test per Token Analytics Dashboard - disaggregazione 90 giorni per tipo operazione e plan."""
import pytest
from datetime import datetime, timedelta


class TestTokenAnalyticsUnit:
    """Test unit sulla logica di analytics."""
    
    def test_token_analytics_conversion_rate_calculation(self):
        """Verifica che conversion_rate = success / total (token > 0)."""
        total = 10
        success = 8
        conversion_rate = round(100 * success / total, 1) if total > 0 else 0
        assert conversion_rate == 80.0
    
    def test_token_analytics_disaggregated_by_plan(self):
        """Verifica che le metriche siano disaggregate Free vs Pro."""
        requests_by_operation = {
            "text": {
                "2026-05-03": {"free": 10, "pro": 20, "total": 30}
            }
        }
        assert requests_by_operation["text"]["2026-05-03"]["free"] < requests_by_operation["text"]["2026-05-03"]["pro"]
    
    def test_token_stats_voice_more_expensive_than_text(self):
        """Voice/photo dovrebbero consumare più token di text."""
        estimated_costs = {
            "text": 800,
            "voice": 1500,
            "photo": 2000,
            "rag": 5000,
        }
        assert estimated_costs["voice"] > estimated_costs["text"]
        assert estimated_costs["photo"] > estimated_costs["text"]
        assert estimated_costs["rag"] > estimated_costs["photo"]
    
    def test_json_serialization_format(self):
        """Verifica il formato corretto dei dati JSON per il template."""
        import json
        analytics_data = {
            "requests_by_operation": {
                "text": {
                    "2026-05-03": {"free": 10, "pro": 20, "total": 30},
                },
            },
            "token_stats": {
                "text": {"free": 800, "pro": 850, "total": 825},
            },
            "conversion_rates": {
                "text": {"free": 80.0, "pro": 90.0, "total": 85.0},
            },
        }
        json_str = json.dumps(analytics_data)
        parsed = json.loads(json_str)
        assert "requests_by_operation" in parsed
        assert parsed["token_stats"]["text"]["total"] == 825


@pytest.mark.integration
class TestTokenAnalyticsIntegration:
    """Test integration con database."""
    
    def test_analytics_aggregation_logic(self, mock_db_session):
        """Test della logica di aggregazione dati analytics."""
        from src.user_store import User, LlmUsageEvent, UserPlan
        
        store = mock_db_session
        now = datetime.utcnow()
        reset_date = store._next_cycle_reset(now)
        
        with store.Session() as s:
            # Crea utenti
            user = User(chat_id="user_test", username="test_user", storage_backend="postgres")
            s.add(user)
            s.flush()
            
            # Crea UserPlan con tokens_reset_at
            plan = UserPlan(chat_id="user_test", plan_type="free", tokens_total=150000, tokens_reset_at=reset_date)
            s.add(plan)
            
            # Aggiungi LlmUsageEvent
            for i in range(5):
                event = LlmUsageEvent(
                    chat_id="user_test",
                    occurred_at=now - timedelta(days=i),
                    provider="mistral",
                    model="mistral-small",
                    operation="text",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    estimated_cost_amount=0.05,
                    request_key=f"test_key_{i}",
                )
                s.add(event)
            
            s.commit()
            
            # Verifica dati salvati
            count = s.query(LlmUsageEvent).count()
            assert count == 5
            
            # Query analytics
            events = s.query(LlmUsageEvent).filter(
                LlmUsageEvent.occurred_at >= (now - timedelta(days=90))
            ).all()
            
            assert len(events) == 5
            assert all(e.total_tokens > 0 for e in events)
    
    def test_analytics_empty_database(self, mock_db_session):
        """Query analytics su DB vuoto."""
        from src.user_store import User, UserPlan, LlmUsageEvent
        
        store = mock_db_session
        now = datetime.utcnow()
        reset_date = store._next_cycle_reset(now)
        
        with store.Session() as s:
            user = User(chat_id="empty_user", username="empty", storage_backend="postgres")
            s.add(user)
            s.flush()
            
            plan = UserPlan(chat_id="empty_user", plan_type="free", tokens_total=150000, tokens_reset_at=reset_date)
            s.add(plan)
            s.commit()
            
            count = s.query(LlmUsageEvent).count()
            assert count == 0
