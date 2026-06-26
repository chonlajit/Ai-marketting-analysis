import os
from app.database import SessionLocal
from app.models import Setting

db = SessionLocal()
settings = db.query(Setting).filter(Setting.key.in_(['telegram_bot_token', 'telegram_chat_id'])).all()
for s in settings:
    print(f"{s.key}: {s.value}")

db.close()
