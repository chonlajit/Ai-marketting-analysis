from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from app.database import get_db, engine, Base, SessionLocal, log_event
from app.models import NewsItem, FeedConfig, Setting, LogEntry
from app.config import DEFAULT_SETTINGS, DEFAULT_FEEDS
from app.worker import start_scheduler, stop_scheduler, restart_scheduler, execution_cycle
from app.ai_processor import filter_news, analyze_news
from app.telegram_publisher import send_to_telegram, get_telegram_credentials
import httpx

def init_db():
    """Initializes tables and seeds default values if they are missing."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed settings
        for key, value in DEFAULT_SETTINGS.items():
            exists = db.query(Setting).filter(Setting.key == key).first()
            if not exists:
                db.add(Setting(key=key, value=value))
                
        # Seed feeds
        for f in DEFAULT_FEEDS:
            exists = db.query(FeedConfig).filter(FeedConfig.url == f["url"]).first()
            if not exists:
                db.add(FeedConfig(
                    name=f["name"],
                    url=f["url"],
                    tier=f["tier"],
                    is_calendar=f.get("is_calendar", False),
                    active=f["active"]
                ))
        db.commit()
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Seed database and boot background scheduler
    init_db()
    start_scheduler()
    yield
    # Shutdown: Turn off background scheduler
    stop_scheduler()

app = FastAPI(
    title="AI Financial News Intelligence Platform API",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- APIs ---

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Retrieves count statistics for the Dashboard."""
    total_news = db.query(NewsItem).count()
    important_news = db.query(NewsItem).filter(NewsItem.is_important == True).count()
    noise_news = db.query(NewsItem).filter(NewsItem.is_important == False).count()
    pending_news = db.query(NewsItem).filter(NewsItem.is_important == None).count()
    telegram_sent = db.query(NewsItem).filter(NewsItem.telegram_sent == True).count()
    active_feeds = db.query(FeedConfig).filter(FeedConfig.active == True).count()
    
    # Calculate asset sentiment metrics for the last 48 hours
    cutoff = datetime.utcnow() - timedelta(hours=48)
    analyzed_items = db.query(NewsItem).filter(
        NewsItem.is_important == True, 
        NewsItem.ai_analysis != None,
        NewsItem.published_at >= cutoff
    ).all()
    
    sentiment = {
        "USD": {"pos": 0, "neg": 0, "neu": 0},
        "Gold": {"pos": 0, "neg": 0, "neu": 0},
        "Nasdaq": {"pos": 0, "neg": 0, "neu": 0},
        "SP500": {"pos": 0, "neg": 0, "neu": 0}
    }
    
    for item in analyzed_items:
        assets = item.ai_analysis.get("assets", {})
        for asset in sentiment.keys():
            impact = assets.get(asset, {}).get("impact", "0")
            if impact == "+":
                sentiment[asset]["pos"] += 1
            elif impact == "-":
                sentiment[asset]["neg"] += 1
            else:
                sentiment[asset]["neu"] += 1
                
    return {
        "total_fetched": total_news,
        "important_count": important_news,
        "noise_count": noise_news,
        "pending_count": pending_news,
        "telegram_sent": telegram_sent,
        "active_feeds": active_feeds,
        "sentiment_48h": sentiment
    }

@app.get("/api/news")
def get_news(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    is_important: Optional[bool] = Query(None),
    is_calendar: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Lists news items with filters."""
    query = db.query(NewsItem)
    
    if is_important is not None:
        query = query.filter(NewsItem.is_important == is_important)
    if is_calendar is not None:
        query = query.filter(NewsItem.is_calendar == is_calendar)
    if source:
        query = query.filter(NewsItem.source == source)
    if search:
        query = query.filter(NewsItem.title.contains(search) | NewsItem.raw_content.contains(search))
        
    total = query.count()
    items = query.order_by(desc(NewsItem.published_at)).limit(limit).offset(offset).all()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }

@app.get("/api/news/{item_id}")
def get_news_detail(item_id: int, db: Session = Depends(get_db)):
    """Retrieves detailed news item."""
    item = db.query(NewsItem).filter(NewsItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
    return item

@app.post("/api/news/{item_id}/analyze")
def trigger_manual_analysis(item_id: int, db: Session = Depends(get_db)):
    """Triggers manual AI analysis for a specific news item."""
    item = db.query(NewsItem).filter(NewsItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
        
    log_event(db, "INFO", "API", f"Manual analysis triggered for item: {item.title[:40]}...")
    
    # Mark as important first if it wasn't
    if not item.is_important:
        item.is_important = True
        
    success = analyze_news(db, item)
    if not success:
        raise HTTPException(status_code=500, detail="AI Analysis failed. Check logs for details.")
        
    return {"message": "AI Analysis successful", "item": item}

@app.post("/api/news/{item_id}/send-telegram")
def trigger_manual_telegram_send(item_id: int, db: Session = Depends(get_db)):
    """Manually sends an analyzed news report to Telegram."""
    item = db.query(NewsItem).filter(NewsItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
        
    if not item.ai_analysis:
        raise HTTPException(status_code=400, detail="News item must be analyzed by AI before sending to Telegram")
        
    log_event(db, "INFO", "API", f"Manual Telegram dispatch triggered for item: {item.title[:40]}...")
    success = send_to_telegram(db, item)
    
    if not success:
        raise HTTPException(status_code=500, detail="Telegram dispatch failed. Check credentials and logs.")
        
    return {"message": "Telegram message sent successfully", "telegram_sent_at": item.telegram_sent_at}

# --- Settings ---

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    """Retrieves setting key-values."""
    settings = db.query(Setting).all()
    return {s.key: s.value for s in settings}

@app.put("/api/settings")
def update_settings(updates: dict, db: Session = Depends(get_db)):
    """Updates setting key-values and triggers worker reconfigurations if needed."""
    log_event(db, "INFO", "API", "Updating system settings...")
    
    interval_changed = False
    worker_toggle = False
    
    for key, value in updates.items():
        setting = db.query(Setting).filter(Setting.key == key).first()
        if setting:
            if key == "fetch_interval_minutes" and setting.value != str(value):
                interval_changed = True
            if key == "worker_active" and setting.value != str(value).lower():
                worker_toggle = True
                
            setting.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
            
    db.commit()
    
    # If key background settings changed, restart the scheduler
    if interval_changed or worker_toggle:
        restart_scheduler()
        
    return {"message": "Settings updated successfully"}

@app.post("/api/settings/test-telegram")
def test_telegram_connection(db: Session = Depends(get_db)):
    """Sends a mock test message to Telegram to verify credentials."""
    bot_token, chat_id = get_telegram_credentials(db)
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail="Telegram credentials are not configured")
        
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🔌 <b>FinAI Connection Test</b>\n\nYour Telegram Bot integration with the <b>FinAI Financial Intelligence Platform</b> is configured correctly! 🚀\n\nTimestamp: <code>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
            "parse_mode": "HTML"
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            
        return {"message": "Test message sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Telegram API Error: {str(e)}")

# --- Feeds ---

@app.get("/api/feeds")
def get_feeds(db: Session = Depends(get_db)):
    """Retrieves all feed configurations."""
    return db.query(FeedConfig).order_by(FeedConfig.tier.asc()).all()

@app.post("/api/feeds")
def add_feed(feed: dict, db: Session = Depends(get_db)):
    """Adds a new feed configuration."""
    name = feed.get("name")
    url = feed.get("url")
    tier = feed.get("tier", 1)
    is_calendar = feed.get("is_calendar", False)
    active = feed.get("active", True)
    
    if not name or not url:
        raise HTTPException(status_code=400, detail="Name and URL are required")
        
    exists = db.query(FeedConfig).filter(FeedConfig.url == url).first()
    if exists:
        raise HTTPException(status_code=400, detail="Feed URL already exists")
        
    new_feed = FeedConfig(name=name, url=url, tier=tier, is_calendar=is_calendar, active=active)
    db.add(new_feed)
    db.commit()
    log_event(db, "INFO", "API", f"Added new feed: {name} ({url})")
    
    # Reconfigure scheduler if we added feeds
    restart_scheduler()
    return new_feed

@app.put("/api/feeds/{feed_id}")
def update_feed(feed_id: int, updates: dict, db: Session = Depends(get_db)):
    """Updates feed configuration."""
    feed = db.query(FeedConfig).filter(FeedConfig.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
        
    if "name" in updates: feed.name = updates["name"]
    if "url" in updates: feed.url = updates["url"]
    if "tier" in updates: feed.tier = int(updates["tier"])
    if "is_calendar" in updates: feed.is_calendar = bool(updates["is_calendar"])
    if "active" in updates: feed.active = bool(updates["active"])
    
    db.commit()
    log_event(db, "INFO", "API", f"Updated feed: {feed.name}")
    
    # Reconfigure scheduler if feeds changed
    restart_scheduler()
    return feed

@app.delete("/api/feeds/{feed_id}")
def delete_feed(feed_id: int, db: Session = Depends(get_db)):
    """Deletes feed configuration."""
    feed = db.query(FeedConfig).filter(FeedConfig.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
        
    log_event(db, "INFO", "API", f"Deleted feed: {feed.name}")
    db.delete(feed)
    db.commit()
    
    # Reconfigure scheduler
    restart_scheduler()
    return {"message": "Feed deleted successfully"}

# --- Logs ---

@app.get("/api/logs")
def get_logs(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    """Retrieves recent system logs."""
    return db.query(LogEntry).order_by(desc(LogEntry.timestamp)).limit(limit).all()

# --- Worker Override ---

@app.post("/api/worker/run")
def run_worker_now(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually triggers a news fetch and analyze worker cycle in the background."""
    log_event(db, "INFO", "API", "Manual background execution cycle requested by user.")
    background_tasks.add_task(execution_cycle)
    return {"message": "Background worker process started."}

# --- Static File Serving ---

# Static files mount
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    """Serves the dashboard home HTML file."""
    return FileResponse("static/index.html")
