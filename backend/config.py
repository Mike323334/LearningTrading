import os
from pathlib import Path

from dotenv import load_dotenv

# Alpaca API credentials — get free paper-trading keys at
# https://app.alpaca.markets/signup, then Paper Trading > API Keys.
# No funding required; market data works fine on the free/paper tier.
#
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "TradingApp/1.0 contact@example.com")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")