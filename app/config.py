import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

import urllib.parse

def parse_and_safe_url(url_str):
    if not url_str:
        return url_str
    # Remove Prisma-specific pgbouncer parameter which psycopg2 does not support
    url_str = url_str.replace("?pgbouncer=true", "").replace("&pgbouncer=true", "")
    
    # Convert postgres:// to postgresql://
    if url_str.startswith("postgres://"):
        url_str = url_str.replace("postgres://", "postgresql://", 1)

        
    if not url_str.startswith("postgresql://"):
        return url_str
        
    try:
        prefix = "postgresql://"
        rest = url_str[len(prefix):]
        # Split by the last '@' to separate credentials from host info
        if "@" in rest:
            creds, host_part = rest.rsplit("@", 1)
            if ":" in creds:
                username, password = creds.split(":", 1)
                # URL encode password to handle special characters (e.g. '@', ':', '/')
                safe_password = urllib.parse.quote_plus(password)
                return f"{prefix}{username}:{safe_password}@{host_part}"
    except Exception:
        pass
    return url_str

DATABASE_URL = parse_and_safe_url(os.getenv("DATABASE_URL", f"sqlite:///{INSTANCE_DIR}/database.db"))



# Default configuration settings
DEFAULT_SETTINGS = {
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "model_name": os.getenv("AI_MODEL_NAME", "gemini-2.5-flash-lite"),
    "fetch_interval_minutes": "5",
    "filter_confidence_threshold": "70",  # Minimum confidence (0-100) to auto-post
    "worker_active": "true",
    "pre_event_alert_active": "true",
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
        "url": "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
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
