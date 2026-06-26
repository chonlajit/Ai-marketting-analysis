import time
import httpx
from datetime import datetime, timedelta
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

def send_report_to_chat(bot_token: str, chat_id: str, report_text: str):
    """Sends a summary report message to a specific Telegram chat."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": report_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except Exception as e:
        print(f"Error sending report to chat: {e}")

def run_and_report(chat_id: str, bot_token: str):
    """Runs a full news fetch + analysis cycle and sends a Thai summary report to the requester."""
    db = SessionLocal()
    module_name = "Worker: Run & Report"
    report_lines = []
    high_impact_items = []
    noise_items = []
    
    try:
        # Check if worker is paused
        active_setting = db.query(Setting).filter(Setting.key == "worker_active").first()
        if active_setting and active_setting.value.lower() != "true":
            send_report_to_chat(bot_token, chat_id,
                "⏸️ <b>กระผม Markus Anna ขอเรียนแจ้งว่า Worker ของระบบถูกหยุดพักอยู่ขณะนี้ครับผม</b>\n\nกรุณาไปที่หน้าตั้งค่าเว็บและเปิด Worker Active ก่อนนะครับ")
            return

        log_event(db, "INFO", module_name, f"Starting run_and_report cycle for chat_id={chat_id}")
        
        # Step 1: Fetch news
        fetch_results = fetch_all(db)
        new_count = fetch_results.get("added_count", 0)
        
        # Step 2: Process pending items and collect results
        pending_items = db.query(NewsItem).filter(NewsItem.is_important == None).order_by(NewsItem.published_at.asc()).all()
        
        for item in pending_items:
            is_important = filter_news(db, item)
            time.sleep(4.0)
            
            # Collect filter metadata (new fields from updated prompt)
            pct = getattr(item, "importance_percent", None)
            gold_lvl = getattr(item, "gold_impact_level", None)
            pub_date = item.published_at.strftime("%d/%m %H:%M") if item.published_at else "?"
            
            if is_important:
                analyzed = analyze_news(db, item)
                time.sleep(4.0)
                if analyzed:
                    score = item.ai_analysis.get("importance_score", "?") if item.ai_analysis else "?"
                    conf  = item.ai_analysis.get("confidence_score", "?") if item.ai_analysis else "?"
                    gold_dir = ""
                    if item.ai_analysis and "assets" in item.ai_analysis:
                        g = item.ai_analysis["assets"].get("Gold", {})
                        gold_dir = g.get("impact", "")
                    high_impact_items.append((item.title, score, conf, pct, gold_lvl, gold_dir, pub_date))
                    send_to_telegram(db, item)
            else:
                noise_items.append((item.title, pct, gold_lvl, pub_date))
        
        # Step 3: Build report message
        total_scanned = len(pending_items)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        if total_scanned == 0 and new_count == 0:
            report = (
                f"🎩 <b>รายงานสรุปการสแกนจากกระผม Markus Anna ครับผม</b>\n"
                f"🕐 เวลาสแกน: {now_str}\n\n"
                "📭 ไม่พบข่าวสารใหม่ในรอบนี้เลยครับผม ทุกข่าวได้รับการประมวลผลครบถ้วนแล้ว\n\n"
                "<i>กระผมจะคอยเฝ้าระวังและรายงานให้ท่านทราบทันทีที่มีข่าวสำคัญเกิดขึ้นครับ</i>"
            )
        else:
            report = f"🎩 <b>รายงานสรุปการสแกนจากกระผม Markus Anna ครับผม</b>\n"
            report += f"🕐 เวลาสแกน: {now_str}\n"
            report += f"📥 ข่าวใหม่เข้าระบบ: <b>{new_count} รายการ</b> | ประมวลผล AI: <b>{total_scanned} รายการ</b>\n\n"
            
            if high_impact_items:
                report += f"🚨 <b>ข่าวสำคัญ High Impact ({len(high_impact_items)} รายการ) — ส่งแจ้งเตือนแล้วขอรับ:</b>\n"
                for title, score, conf, pct, gold_lvl, gold_dir, pub_date in high_impact_items:
                    gold_arrow = {"+" : "📈", "-": "📉", "0": "➡️"}.get(gold_dir, "❓")
                    pct_str = f"{pct}%" if pct is not None else "?"
                    gold_str = f"{gold_arrow} {gold_lvl}" if gold_lvl else gold_arrow
                    report += (
                        f"  🔴 [{pub_date}] {title[:55]}{'...' if len(title) > 55 else ''}\n"
                        f"       📊 ความสำคัญ: <b>{pct_str}</b> | ผลทอง: <b>{gold_str}</b> | Score: <b>{score}/10</b>\n"
                    )
                report += "\n"
            
            if noise_items:
                report += f"📋 <b>ข่าวทั่วไปที่คัดออก Noise ({len(noise_items)} รายการ):</b>\n"
                show_noise = noise_items[:8]
                for title, pct, gold_lvl, pub_date in show_noise:
                    pct_str = f"{pct}%" if pct is not None else "?"
                    gold_str = gold_lvl if gold_lvl else "?"
                    report += (
                        f"  ⚫ [{pub_date}] {title[:50]}{'...' if len(title) > 50 else ''}\n"
                        f"       📊 ความสำคัญ: {pct_str} | ผลทอง: {gold_str}\n"
                    )
                if len(noise_items) > 8:
                    report += f"  <i>...และอีก {len(noise_items) - 8} รายการ</i>\n"
            
            if not high_impact_items and total_scanned > 0:
                report += "\n✅ <b>ไม่พบข่าวที่มีผลกระทบสูงในรอบนี้ครับผม</b> ตลาดยังเคลื่อนไหวปกติอยู่นะครับ\n"
            
            report += "\n<i>กระผมจะคอยเฝ้าระวังและแจ้งเตือนอัตโนมัติทุก 5 นาทีครับผม 🎩</i>"
        
        send_report_to_chat(bot_token, chat_id, report)
        log_event(db, "INFO", module_name, f"Sent run report to chat_id={chat_id}. High impact: {len(high_impact_items)}, Noise: {len(noise_items)}")
        
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Error in run_and_report: {str(e)}")
        send_report_to_chat(bot_token, chat_id,
            f"⚠️ <b>กระผม Markus Anna ขอรายงานว่าเกิดข้อผิดพลาดในระหว่างการประมวลผลครับผม</b>\n\n<code>{str(e)[:200]}</code>")
    finally:
        db.close()

def process_pending_items(db: Session):
    """Processes news items that are pending filtering, analysis, or Telegram dispatch."""
    from sqlalchemy import text
    module_name = "Worker: Main Pipeline"
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    
    # 1. Filter and analyze NEW news items (is_important IS NULL = not yet reviewed)
    pending_items = db.query(NewsItem).filter(
        NewsItem.is_important.is_(None),
        NewsItem.published_at >= cutoff_time  # Only process recent items
    ).order_by(NewsItem.published_at.asc()).all()
    log_event(db, "INFO", module_name, f"Step1 pending filter: {len(pending_items)} items.")
        
    for item in pending_items:
        # Phase 1: Filter
        is_important = filter_news(db, item)
        time.sleep(4.0)  # Sleep to avoid hitting Gemini API rate limits
        
        # Phase 2: If important, analyze
        if is_important:
            analyzed = analyze_news(db, item)
            time.sleep(4.0)  # Sleep to avoid hitting Gemini API rate limits
            if analyzed:
                send_to_telegram(db, item)
                
    # 2. Catch up: Items marked important but NO ai_analysis yet
    un_analyzed = db.query(NewsItem).filter(
        NewsItem.is_important == True,
        NewsItem.ai_analysis.is_(None),
        NewsItem.telegram_sent == False,
        NewsItem.published_at >= cutoff_time  # Only last 24h — don't waste quota on old news
    ).all()
    log_event(db, "INFO", module_name, f"Step2 pending analysis (RSS): {len(un_analyzed)} items.")
    for item in un_analyzed:
        log_event(db, "INFO", module_name, f"Analyzing: {item.title[:50]}")
        analyzed = analyze_news(db, item)
        time.sleep(4.0)
        if analyzed:
            send_to_telegram(db, item)
            
    # (Step 3 removed as all items should now have AI analysis before sending)
    pass
            
    # 4. Catch up: Analyzed but not sent to Telegram yet
    unsent_rss = db.query(NewsItem).filter(
        NewsItem.is_important == True,
        NewsItem.ai_analysis.isnot(None),
        NewsItem.telegram_sent == False,
        NewsItem.published_at >= cutoff_time
    ).all()
    log_event(db, "INFO", module_name, f"Step4 unsent RSS: {len(unsent_rss)} items.")
    for item in unsent_rss:
        log_event(db, "INFO", module_name, f"Sending RSS: {item.title[:50]}")
        send_to_telegram(db, item)

def send_pre_event_alerts(db: Session):
    """
    Checks for upcoming High Impact Forex Factory calendar events
    and sends a single consolidated countdown alert 30 minutes before
    the event time to all Telegram subscribers.
    Zero Gemini API calls - uses only DB data and Telegram API.
    """
    module_name = "Worker: Pre-Event Alert"
    
    try:
        from app.models import Setting
        alert_active = db.query(Setting).filter(Setting.key == "pre_event_alert_active").first()
        if alert_active and alert_active.value.lower() != "true":
            return
            
        from collections import defaultdict
        from app.models import TelegramSubscriber
        from app.telegram_publisher import get_telegram_credentials
        
        bot_token, _ = get_telegram_credentials(db)
        if not bot_token:
            return
        
        subscribers = db.query(TelegramSubscriber).filter(TelegramSubscriber.wants_pre_alerts == True).all()
        if not subscribers:
            return
        
        now_utc = datetime.utcnow()
        
        # Look for High Impact calendar events in the 30-min window (25 to 35 minutes from now)
        start_window = now_utc + timedelta(minutes=25)
        end_window = now_utc + timedelta(minutes=35)
        
        upcoming = db.query(NewsItem).filter(
            NewsItem.is_calendar == True,
            NewsItem.is_important == True,
            NewsItem.published_at >= start_window,
            NewsItem.published_at <= end_window
        ).all()
        
        if not upcoming:
            return
            
        # Filter for items that have NOT sent the 30-min alert yet
        pending_alerts = []
        for item in upcoming:
            sent_map = item.pre_alert_sent or {}
            if not sent_map.get("30"):
                pending_alerts.append(item)
                
        if not pending_alerts:
            return
            
        # Group pending alerts by their exact published_at time
        grouped_by_time = defaultdict(list)
        for item in pending_alerts:
            grouped_by_time[item.published_at].append(item)
            
        # Send one message per time group
        for event_time, items in grouped_by_time.items():
            event_th = event_time + timedelta(hours=7)
            event_time_str = event_th.strftime("%d/%m/%Y %H:%M")
            
            # Calculate actual minutes remaining dynamically
            mins_display = int((event_time - now_utc).total_seconds() / 60)
            if mins_display < 0:
                mins_display = 30
                
            # Build alert message header
            alert_msg = f"⏰ <b>อีกประมาณ {mins_display} นาที! ข่าวสำคัญกำลังจะออกแล้วครับผม</b>\n\n"
            
            # Append each event details
            for item in items:
                details = item.calendar_details or {}
                import html
                country = details.get("country", "")
                forecast = html.escape(str(details.get("forecast", "N/A")))
                previous = html.escape(str(details.get("previous", "N/A")))
                
                flag = {
                    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧",
                    "JPY": "🇯🇵", "CNY": "🇨🇳", "AUD": "🇦🇺",
                    "CAD": "🇨🇦", "CHF": "🇨🇭", "NZD": "🇳🇿"
                }.get(country, "🌍")
                
                clean_title = html.escape(item.title.replace(f"[{country}] ", ""))
                
                alert_msg += (
                    f"{flag} <b>[{country}] {clean_title}</b>\n"
                    f"📅 เวลาประกาศ (ไทย): <b>{event_time_str} น.</b>\n"
                    f"📊 คาดการณ์: <b>{forecast}</b> | ครั้งก่อน: <b>{previous}</b>\n"
                    f"⚡ ระดับผลกระทบ: <b>🔴 HIGH</b>\n\n"
                )
                
            alert_msg += (
                f"🥇 ทองคำและตลาดการเงินอาจเกิดความผันผวนสูง โปรดเตรียมพร้อมรับมือนะครับผม\n"
                f"<i>กระผม Markus Anna จะรายงานผลการวิเคราะห์ทันทีที่ข่าวออกครับผม 🎩</i>"
            )
            
            # Send to all subscribers who want pre alerts
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            for sub in subscribers:
                try:
                    with httpx.Client(timeout=10.0) as client:
                        client.post(url, json={
                            "chat_id": sub.chat_id,
                            "text": alert_msg,
                            "parse_mode": "HTML"
                        })
                except Exception as e:
                    log_event(db, "ERROR", module_name, f"Failed to send pre-alert to {sub.chat_id}: {e}")
            
            # Mark all these items as sent for the 30-min window and log history
            from app.models import MessageHistory
            for item in items:
                new_sent_map = dict(item.pre_alert_sent or {})
                new_sent_map["30"] = True
                item.pre_alert_sent = new_sent_map
                
                # Log to message history
                hist = MessageHistory(
                    news_item_id=item.id,
                    trigger_type="pre_event",
                    reason="แจ้งเตือนนับถอยหลัง 30 นาทีก่อนข่าวออก",
                    status="success"
                )
                db.add(hist)
                
            db.commit()
            
            log_event(db, "INFO", module_name,
                f"Sent 30-min consolidated pre-alert for {len(items)} events to {len(subscribers)} subscribers.")
                
    except Exception as e:
        log_event(db, "ERROR", module_name, f"Error in send_pre_event_alerts: {str(e)}")

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
        
        # Step 3: Pre-event countdown alerts (no Gemini API calls)
        send_pre_event_alerts(db)
        
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
