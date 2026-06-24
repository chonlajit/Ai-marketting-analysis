import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from app.database import SessionLocal, log_event
from app.models import NewsItem, Setting
from app.fetcher import fetch_all
from app.ai_processor import filter_news, analyze_news
from app.telegram_publisher import send_to_telegram

# Global scheduler instance
scheduler = BackgroundScheduler()
is_worker_running = False

def process_pending_items(db: Session):
    """Processes news items that are pending filtering, analysis, or Telegram dispatch."""
    module_name = "Worker: Main Pipeline"
    
    # 1. Filter and analyze new news items
    pending_items = db.query(NewsItem).filter(NewsItem.is_important == None).order_by(NewsItem.published_at.asc()).all()
    if pending_items:
        log_event(db, "INFO", module_name, f"Found {len(pending_items)} pending items to process.")
        
    for item in pending_items:
        # Phase 1: Filter
        is_important = filter_news(db, item)
        time.sleep(4.0)  # Sleep to avoid hitting Gemini API rate limits
        
        # Phase 2: If important, analyze
        if is_important:
            analyzed = analyze_news(db, item)
            time.sleep(4.0)  # Sleep to avoid hitting Gemini API rate limits
            if analyzed:
                # Phase 3: Dispatch to Telegram
                send_to_telegram(db, item)
                
    # 2. Catch up on items that were marked important but failed to analyze
    un_analyzed = db.query(NewsItem).filter(NewsItem.is_important == True, NewsItem.ai_analysis == None).all()
    for item in un_analyzed:
        log_event(db, "INFO", module_name, f"Retrying analysis for: {item.title[:40]}...")
        analyzed = analyze_news(db, item)
        time.sleep(4.0)  # Sleep to avoid hitting Gemini API rate limits
        if analyzed:
            send_to_telegram(db, item)
            
    # 3. Catch up on items that were analyzed but failed Telegram dispatch (due to rate limits or connection drop)
    unsent_items = db.query(NewsItem).filter(NewsItem.is_important == True, NewsItem.ai_analysis != None, NewsItem.telegram_sent == False).all()
    for item in unsent_items:
        log_event(db, "INFO", module_name, f"Retrying Telegram dispatch for: {item.title[:40]}...")
        send_to_telegram(db, item)

def execution_cycle():
    """Main job executed by the scheduler."""
    db = SessionLocal()
    module_name = "Worker: Cycle"
    try:
        # Check if worker is active in settings
        active_setting = db.query(Setting).filter(Setting.key == "worker_active").first()
        if active_setting and active_setting.value.lower() != "true":
            log_event(db, "INFO", module_name, "Background fetcher is currently paused by settings.")
            return

        log_event(db, "INFO", module_name, "Starting news fetch and analysis cycle...")
        
        # Step 1: Fetch from all feeds
        fetch_results = fetch_all(db)
        log_event(db, "INFO", module_name, f"Fetched news. Added {fetch_results['added_count']} new items.")
        
        # Step 2: Process pipeline
        process_pending_items(db)
        
        log_event(db, "INFO", module_name, "Execution cycle completed successfully.")
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Error in execution cycle: {str(e)}")
    finally:
        db.close()

def start_scheduler():
    """Starts the background worker scheduler."""
    global is_worker_running
    db = SessionLocal()
    module_name = "Worker: Control"
    
    try:
        if scheduler.running:
            log_event(db, "INFO", module_name, "Scheduler is already running.")
            return
            
        # Get interval from settings
        interval_setting = db.query(Setting).filter(Setting.key == "fetch_interval_minutes").first()
        interval = int(interval_setting.value) if interval_setting else 5
        
        # Schedule the job
        scheduler.add_job(
            execution_cycle,
            "interval",
            minutes=interval,
            id="fetch_news_job",
            replace_existing=True,
            next_run_time=datetime.now()  # Run immediately on startup
        )
        
        scheduler.start()
        is_worker_running = True
        log_event(db, "INFO", module_name, f"Background worker scheduler started. Fetch interval: {interval} minutes.")
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Failed to start scheduler: {str(e)}")
    finally:
        db.close()

def stop_scheduler():
    """Stops the background worker scheduler."""
    global is_worker_running
    db = SessionLocal()
    module_name = "Worker: Control"
    
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            is_worker_running = False
            log_event(db, "INFO", module_name, "Background worker scheduler stopped.")
        else:
            log_event(db, "INFO", module_name, "Scheduler was not running.")
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Failed to stop scheduler: {str(e)}")
    finally:
        db.close()

def restart_scheduler():
    """Restarts the scheduler with updated interval from settings."""
    db = SessionLocal()
    module_name = "Worker: Control"
    try:
        # Check settings
        interval_setting = db.query(Setting).filter(Setting.key == "fetch_interval_minutes").first()
        interval = int(interval_setting.value) if interval_setting else 5
        
        # Check active status
        active_setting = db.query(Setting).filter(Setting.key == "worker_active").first()
        is_active = active_setting.value.lower() == "true" if active_setting else True
        
        if scheduler.running:
            scheduler.remove_all_jobs()
            
        if is_active:
            scheduler.add_job(
                execution_cycle,
                "interval",
                minutes=interval,
                id="fetch_news_job",
                replace_existing=True
            )
            log_event(db, "INFO", module_name, f"Background worker scheduler reconfigured. Fetch interval: {interval} minutes.")
        else:
            log_event(db, "INFO", module_name, "Scheduler running but no jobs active (worker paused by settings).")
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Failed to restart scheduler: {str(e)}")
    finally:
        db.close()
