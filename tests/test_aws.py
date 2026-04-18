import sys
sys.path.append('.')
from src.dashboard.app import get_aws_monthly_cost
from config import Config

print(f"Key loaded: {Config.AWS_ACCESS_KEY_ID}")
try:
    print("Testing cost...")
    cost = get_aws_monthly_cost()
    print("Cost: ", cost)
except Exception as e:
    print("Error:", e)
