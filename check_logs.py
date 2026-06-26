import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import LogEntry, Setting

db = SessionLocal()

print("--- TELEGRAM SETTINGS ---")
settings = db.query(Setting).filter(Setting.key.in_(['telegram_bot_token', 'telegram_chat_id'])).all()
for s in settings:
    print(f"{s.key}: {s.value}")

print("\n--- RECENT LOGS ---")
logs = db.query(LogEntry).order_by(LogEntry.timestamp.desc()).limit(30).all()
for l in logs:
    print(f"{l.timestamp} [{l.level}] {l.module}: {l.message}")

db.close()
