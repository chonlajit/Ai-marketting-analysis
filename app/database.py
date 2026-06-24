from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import DATABASE_URL
from datetime import datetime

# Check if using SQLite, if so, allow multi-thread access
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def log_event(db, level, module, message):
    try:
        from app.models import LogEntry
        log_entry = LogEntry(timestamp=datetime.utcnow(), level=level, module=module, message=message)
        db.add(log_entry)
        db.commit()
    except Exception as e:
        print(f"Error logging to DB: {e}")

