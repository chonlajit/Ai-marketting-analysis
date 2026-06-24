from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from datetime import datetime
from app.database import Base

class NewsItem(Base):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    source = Column(String(100), nullable=False)
    url = Column(String(500), unique=True, index=True, nullable=False)
    published_at = Column(DateTime, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    raw_content = Column(Text, nullable=True)
    tier = Column(Integer, default=1)
    is_calendar = Column(Boolean, default=False)
    calendar_details = Column(JSON, nullable=True)  # Store event detail like Forecast, Previous, Actual, Impact level
    
    # AI processing steps
    is_important = Column(Boolean, nullable=True)  # True/False/Null (Null = pending)
    filter_reason = Column(Text, nullable=True)
    ai_analysis = Column(JSON, nullable=True)  # Store JSON output: scores for Gold, USD, Nasdaq, S&P500, Thai summary, Confidence, etc.
    
    # Telegram dispatch status
    telegram_sent = Column(Boolean, default=False)
    telegram_sent_at = Column(DateTime, nullable=True)

class FeedConfig(Base):
    __tablename__ = "feed_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), unique=True, nullable=False)
    tier = Column(Integer, default=1)
    is_calendar = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=True)

class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20), default="INFO")
    module = Column(String(50), nullable=True)
    message = Column(Text, nullable=False)
