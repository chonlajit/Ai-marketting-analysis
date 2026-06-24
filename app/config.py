import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{INSTANCE_DIR}/database.db"

# Default configuration settings
DEFAULT_SETTINGS = {
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "fetch_interval_minutes": "5",
    "filter_confidence_threshold": "70",  # Minimum confidence (0-100) to auto-post
    "worker_active": "true",
}

# Initial RSS Feeds list (Tier 1 & Tier 2 defaults)
DEFAULT_FEEDS = [
    # Tier 1
    {
        "name": "Yahoo Finance Markets",
        "url": "https://finance.yahoo.com/rss/markets",
        "tier": 1,
        "active": True
    },
    {
        "name": "Yahoo Finance World Economy",
        "url": "https://finance.yahoo.com/rss/world-economy",
        "tier": 1,
        "active": True
    },
    {
        "name": "Forex Factory Calendar",
        "url": "https://www.forexfactory.com/ff_calendar_thisweek.xml",
        "tier": 1,
        "active": True,
        "is_calendar": True
    },
    # Tier 2
    {
        "name": "CNBC Finance",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "tier": 2,
        "active": False
    },
    {
        "name": "CNBC Economy",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        "tier": 2,
        "active": False
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.content.marketwatch.com/marketwatch/topstories/",
        "tier": 2,
        "active": False
    }
]
