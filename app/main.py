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
from app.models import NewsItem, FeedConfig, Setting, LogEntry, TelegramSubscriber
from app.config import DEFAULT_SETTINGS, DEFAULT_FEEDS
from app.worker import start_scheduler, stop_scheduler, restart_scheduler, execution_cycle, run_and_report
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
    
    # Auto register webhook if RENDER_EXTERNAL_URL is available
    import os
    external_url = os.getenv("RENDER_EXTERNAL_URL")
    if external_url:
        db = SessionLocal()
        try:
            bot_token, _ = get_telegram_credentials(db)
            if bot_token:
                webhook_url = f"{external_url.rstrip('/')}/api/telegram/webhook"
                register_url = f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}"
                # Register webhook with Telegram
                with httpx.Client(timeout=10.0) as client:
                    r = client.post(register_url)
                    log_event(db, "INFO", "Lifespan", f"Auto-registered Telegram Webhook to: {webhook_url}. Response: {r.text}")
        except Exception as e:
            print(f"Failed to auto-register Telegram Webhook: {e}")
        finally:
            db.close()
            
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

# --- Telegram Webhook API ---

@app.post("/api/telegram/webhook")
async def telegram_webhook(update: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Receives commands from Telegram and replies."""
    message = update.get("message", {})
    text = message.get("text", "").strip()
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "private")  # "private", "group", "supergroup", "channel"
    
    if not text or not chat_id:
        return {"status": "ok"}
        
    bot_token, _ = get_telegram_credentials(db)
    if not bot_token:
        return {"status": "no token"}
    
    # --- Group/Supergroup: Block all commands ---
    # Groups only receive automatic alerts. Commands are for private chats only (premium tier).
    if chat_type in ("group", "supergroup", "channel") and text.startswith("/"):
        reply_text = (
            "🎩 <b>กระผม Markus Anna ขอเรียนแจ้งด้วยความสุภาพครับผม</b>\n\n"
            "การใช้งานคำสั่งในกลุ่มยังไม่เปิดให้บริการในแพ็คเกจนี้นะครับ\n"
            "ในกลุ่มนี้ กระผมจะทำหน้าที่ส่ง <b>รายงานข่าวสารอัตโนมัติ</b> เมื่อมีข่าวสำคัญเท่านั้นครับผม\n\n"
            "หากท่านต้องการใช้งานคำสั่งพิเศษทั้งหมด กรุณาติดต่อกระผมผ่าน <b>แชทส่วนตัว</b> นะครับผม 🙏"
        )
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": chat_id, "text": reply_text, "parse_mode": "HTML"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload)
        except Exception as e:
            print(f"Error sending group block reply: {e}")
        return {"status": "ok"}
        
    # Process commands (private chat only)
    if text.startswith("/"):
        command = text.split()[0].lower()
        
        reply_text = ""
        if command in ["/start", "/help"]:
            if command == "/start":
                # Check if already subscribed
                exists = db.query(TelegramSubscriber).filter(TelegramSubscriber.chat_id == str(chat_id)).first()
                if not exists:
                    username = chat.get("username") or chat.get("first_name") or "User"
                    new_sub = TelegramSubscriber(chat_id=str(chat_id), username=username)
                    db.add(new_sub)
                    db.commit()
                    log_event(db, "INFO", "Telegram Webhook", f"New user subscribed: {username} ({chat_id})")
                    reply_text = (
                        "🎩 <b>ยินดีต้อนรับสู่ระบบรายงานข่าวสารของกระผม Markus Anna ครับผม</b>\n\n"
                        "กระผมได้จดบันทึกและลงทะเบียนช่องแชตของท่านเข้าสู่ระบบ <b>รับรายงานข่าวสารเศรษฐกิจสำคัญอัตโนมัติ</b> เรียบร้อยแล้วขอรับ! "
                        "กระผมจะส่งสรุปข่าวสารการเงินโลก และวิเคราะห์ทิศทางผลกระทบต่อราคาสินทรัพย์อย่างรวดเร็วและนุ่มนวลที่สุดให้ท่านทราบเมื่อมีข่าวที่มีระดับความสำคัญสูง (High Impact) นะครับ 🚀\n\n"
                        "ท่านสามารถพิมพ์คำสั่ง /help เพื่อเรียกดูคำสั่งอื่นๆ ทั้งหมด หรือพิมพ์ /stop เพื่อยกเลิกการรับรายงานจากกระผมได้ทุกเมื่อตามที่ท่านต้องการครับผม"
                    )
                else:
                    reply_text = (
                        "🎩 <b>ท่านอยู่ในระบบรับข่าวสารอัตโนมัติของกระผม Markus Anna เรียบร้อยแล้วครับผม</b>\n\n"
                        "หากประสงค์จะศึกษาคำสั่งเพิ่มเติม กรุณาพิมพ์ /help หรือพิมพ์ /stop เพื่อขอยกเลิกการรับรายงานจากกระผมได้ครับผม"
                    )
            else:
                reply_text = (
                    "🎩 <b>กระผม Markus Anna ยินดีที่จะช่วยเหลือและบริการท่านครับ</b>\n\n"
                    "ท่านสามารถสั่งการกระผมผ่านคำสั่งดังต่อไปนี้ได้เลยครับ:\n"
                    "• /stats - เรียกดูสถิติโดยรวมของระบบ FinAI\n"
                    "• /latest - เรียกดูสรุปวิเคราะห์ข่าวเด่นล่าสุด 3 รายการ\n"
                    "• /run - สั่งการให้กระผมค้นหาและวิเคราะห์ข่าวสารใหม่ในทันที\n"
                    "• /stop - ขอยกเลิกการรับรายงานข่าวสารอัตโนมัติชั่วคราว"
                )
        elif command == "/stats":
            total_news = db.query(NewsItem).count()
            important_news = db.query(NewsItem).filter(NewsItem.is_important == True).count()
            noise_news = db.query(NewsItem).filter(NewsItem.is_important == False).count()
            active_feeds = db.query(FeedConfig).filter(FeedConfig.active == True).count()
            
            reply_text = (
                "📊 <b>รายงานสถิติของระบบโดยกระผม Markus Anna ครับผม</b>\n\n"
                f"• ข่าวที่จัดเก็บและกรองทั้งหมด: <b>{total_news} รายการ</b>\n"
                f"• ข่าวสำคัญวิเคราะห์เสร็จสิ้น (High Impact): <b>{important_news} รายการ</b>\n"
                f"• ข่าวสารทั่วไปที่เป็นเสียงรบกวน (Noise): <b>{noise_news} รายการ</b>\n"
                f"• แหล่งข้อมูลข่าวสารที่ทำงานอยู่: <b>{active_feeds} ช่องทางขอรับ</b>"
            )
        elif command == "/latest":
            items = db.query(NewsItem).filter(NewsItem.is_important == True, NewsItem.ai_analysis != None).order_by(desc(NewsItem.published_at)).limit(3).all()
            if not items:
                reply_text = "📭 กระผมยังไม่พบข้อมูลการวิเคราะห์ข่าวสำคัญระดับสูงในระบบ ณ ขณะนี้เลยครับผม"
            else:
                reply_text = "🔥 <b>รายงานวิเคราะห์ข่าวสำคัญล่าสุด 3 อันดับ โดย Markus Anna ครับผม:</b>\n\n"
                for idx, item in enumerate(items):
                    analysis = item.ai_analysis
                    assets = analysis.get("assets", {})
                    summary = analysis.get("summary", {})
                    
                    def get_dir_icon(imp):
                        return "🟢↑" if imp == "+" else ("🔴↓" if imp == "-" else "⚪→")
                        
                    usd = get_dir_icon(assets.get("USD", {}).get("impact"))
                    gold = get_dir_icon(assets.get("Gold", {}).get("impact"))
                    
                    reply_text += f"{idx+1}. <b>{item.title}</b>\n"
                    reply_text += f"💬 <i>{summary.get('what_happened', '-')}</i>\n"
                    reply_text += f"📊 USD: {usd} | Gold: {gold}\n"
                    reply_text += f"🔗 <a href='{item.url}'>ศึกษาเนื้อหาข่าวฉบับเต็ม</a>\n\n"
        elif command == "/run":
            # Run background worker cycle and send report back to this chat
            background_tasks.add_task(run_and_report, str(chat_id), bot_token)
            reply_text = "🔄 <b>กระผม Markus Anna ได้รับคำสั่งแล้วครับผม!</b>\n\nกระผมกำลังเริ่มสแกนและวิเคราะห์ข่าวสารด้วย AI อยู่ขณะนี้ครับ กรุณารอสักครู่ กระผมจะส่งรายงานสรุปผลการสแกนกลับมาให้ท่านทันทีที่เสร็จสิ้นนะครับผม 🎩"
        elif command == "/stop":
            exists = db.query(TelegramSubscriber).filter(TelegramSubscriber.chat_id == str(chat_id)).first()
            if exists:
                db.delete(exists)
                db.commit()
                log_event(db, "INFO", "Telegram Webhook", f"User unsubscribed: {exists.username} ({chat_id})")
                reply_text = "🔕 <b>กระผมได้ดำเนินการยกเลิกการส่งรายงานข่าวสารอัตโนมัติให้ท่านเรียบร้อยแล้วครับผม</b>\n\nระบบได้ลบข้อมูลห้องแชตนี้ออกจากรายชื่อผู้รับข้อมูลเรียบร้อยแล้ว หากท่านมีความประสงค์จะเริ่มต้นรับรายงานจากกระผมใหม่อีกครั้งในภายหลัง สามารถพิมพ์คำสั่ง /start ได้ทุกเมื่อเลยนะครับกระผม"
            else:
                reply_text = "🤖 ท่านยังไม่ได้อยู่ในรายชื่อผู้รับรายงานข่าวสารอัตโนมัติของกระผมเลยนะครับ หากสนใจเริ่มต้นรับข้อมูล โปรดพิมพ์คำสั่ง /start ได้เลยขอรับ"
            
        if reply_text:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": reply_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                # Send reply message to Telegram asynchronously
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json=payload)
            except Exception as e:
                print(f"Error sending webhook reply: {e}")
                
    return {"status": "ok"}

# --- Static File Serving ---

# Static files mount
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    """Serves the dashboard home HTML file."""
    return FileResponse("static/index.html")
