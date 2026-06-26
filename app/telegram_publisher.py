import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import NewsItem, Setting
from app.database import log_event
import html

def get_telegram_credentials(db: Session):
    """Retrieves Telegram Credentials from DB or Environment."""
    token_setting = db.query(Setting).filter(Setting.key == "telegram_bot_token").first()
    bot_token = token_setting.value if token_setting else ""
    
    chat_setting = db.query(Setting).filter(Setting.key == "telegram_chat_id").first()
    chat_id = chat_setting.value if chat_setting else ""
    
    if not bot_token or not chat_id:
        import os
        bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        
    return bot_token, chat_id

def format_telegram_message(item: NewsItem) -> str:
    """Formats news and AI analysis into a beautiful HTML Telegram message."""
    analysis = item.ai_analysis
    if not analysis:
        return f"🎩 🚨 <b>รายงานข่าวสารจากกระผม Markus Anna ครับผม:</b>\n\n📰 <b>{item.title}</b>\n\n{item.raw_content}\n\n🔗 <a href='{item.url}'>อ่านข่าวต้นฉบับ (Full Article)</a>"
        
    importance = analysis.get("importance_score", 5)
    confidence = analysis.get("confidence_score", 50)
    assets = analysis.get("assets", {})
    summary = analysis.get("summary", {})
    reasoning = analysis.get("reasoning_chain", "")
    
    # Header logic based on importance score
    if importance >= 8:
        header = "🎩 🚨 <b>[ด่วนที่สุด] กระผม Markus Anna ขอรายงานข่าวสำคัญยิ่งครับผม</b>"
    elif importance >= 5:
        header = "🎩 ⚠️ <b>[ข่าวสำคัญ] กระผม Markus Anna ขอรายงานสถานการณ์สำคัญครับผม</b>"
    else:
        header = "🎩 📊 <b>กระผม Markus Anna ขอรายงานข่าวสารการเงินทั่วไปครับผม</b>"
        
    # Asset impact direction icons
    def get_dir_icon(impact):
        if impact == "+":
            return "🟢 <b>↑ (บวก)</b>"
        elif impact == "-":
            return "🔴 <b>↓ (ลบ)</b>"
        else:
            return "⚪ <b>→ (ปกติ)</b>"
            
    usd_impact = get_dir_icon(assets.get("USD", {}).get("impact"))
    gold_impact = get_dir_icon(assets.get("Gold", {}).get("impact"))
    nasdaq_impact = get_dir_icon(assets.get("Nasdaq", {}).get("impact"))
    sp500_impact = get_dir_icon(assets.get("SP500", {}).get("impact"))
    
    # Format local time (UTC+7 for Thailand)
    from datetime import timedelta
    local_time = item.published_at + timedelta(hours=7)
    time_str = local_time.strftime('%d/%m/%Y %H:%M')

    # Get importance percent from filter step
    imp_percent_str = f" ({item.importance_percent}%)" if item.importance_percent else ""

    # Escape dangerous characters for Telegram HTML
    safe_title = html.escape(item.title)
    safe_source = html.escape(item.source)
    safe_happened = html.escape(summary.get('what_happened', '-'))
    safe_affects = html.escape(summary.get('what_it_affects', '-'))
    safe_watch = html.escape(summary.get('what_to_watch_next', '-'))
    safe_reasoning = html.escape(reasoning)

    # Build text
    msg = f"{header}\n"
    msg += f"📰 <b>{safe_title}</b>\n"
    msg += f"📅 วันที่/เวลา (ไทย): <b>{time_str}</b>\n"
    msg += f"📍 แหล่งที่มา: {safe_source}\n\n"
    
    if item.is_calendar and item.calendar_details:
        cal = item.calendar_details
        msg += "📊 <b>ตัวเลขเศรษฐกิจ (Economic Data):</b>\n"
        msg += f"• ประเทศ: <b>{cal.get('country')}</b>\n"
        msg += f"• คาดการณ์ (Forecast): <code>{cal.get('forecast')}</code>\n"
        msg += f"• ครั้งก่อน (Previous): <code>{cal.get('previous')}</code>\n\n"
        
    msg += "📊 <b>ดัชนีวิเคราะห์ผลกระทบ (Market Impact):</b>\n"
    msg += f"• 💵 <b>USD</b>: {usd_impact}\n"
    msg += f"• 🏆 <b>Gold</b>: {gold_impact}\n"
    msg += f"• 📈 <b>Nasdaq</b>: {nasdaq_impact}\n"
    msg += f"• 📊 <b>S&P 500</b>: {sp500_impact}\n\n"
    
    msg += "🇹🇭 <b>สรุปประเด็นสำคัญ (Thai Summary):</b>\n"
    msg += f"🔹 <b>เหตุการณ์:</b> {safe_happened}\n"
    msg += f"🔹 <b>ส่งผลต่อ:</b> {safe_affects}\n"
    msg += f"🔹 <b>สิ่งที่ต้องจับตา:</b> {safe_watch}\n\n"
    
    if reasoning:
        msg += "🧠 <b>ขั้นตอนวิเคราะห์ (Reasoning Chain):</b>\n"
        msg += f"<code>{safe_reasoning}</code>\n\n"
        
    msg += f"🎯 ความมั่นใจ: <b>{confidence}%</b> | คะแนนความสำคัญ: <b>{importance}/10</b>{imp_percent_str}\n"
    msg += f"🔗 <a href='{item.url}'>อ่านข่าวต้นฉบับ (Full Article)</a>"
    
    return msg

def send_to_telegram(db: Session, item: NewsItem, trigger_type: str = "auto", reason: str = "ระบบวิเคราะห์อัตโนมัติพบว่าสำคัญ") -> bool:
    """Sends formatted HTML report to the configured Telegram channel/group and all active subscribers."""
    module_name = "Telegram Publisher"
    
    # Import TelegramSubscriber here to avoid circular imports
    from app.models import TelegramSubscriber
    
    bot_token, default_chat_id = get_telegram_credentials(db)
    if not bot_token:
        log_event(db, "ERROR", module_name, "Telegram Bot Token is not configured.")
        return False
        
    # Get all active subscribers
    try:
        subscribers = db.query(TelegramSubscriber).all()
        subscriber_chat_ids = [sub.chat_id for sub in subscribers]
    except Exception as e:
        subscriber_chat_ids = []
        log_event(db, "WARNING", module_name, f"Could not fetch subscribers from DB: {e}")
        
    # Build unique set of destinations
    destinations = set()
    if default_chat_id:
        destinations.add(default_chat_id)
    for cid in subscriber_chat_ids:
        destinations.add(cid)
        
    if not destinations:
        log_event(db, "WARNING", module_name, "No Telegram destinations (channel or subscribers) available.")
        return False
        
    text = format_telegram_message(item)
    success_count = 0
    
    with httpx.Client(timeout=12.0) as client:
        for chat_id in destinations:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                response = client.post(url, json=payload)
                response.raise_for_status()
                success_count += 1
            except Exception as e:
                log_event(db, "ERROR", module_name, f"Failed to send to destination {chat_id}: {str(e)}")
                
    if success_count > 0:
        try:
            # Update database status
            item.telegram_sent = True
            item.telegram_sent_at = datetime.utcnow()
            
            # Log to MessageHistory
            from app.models import MessageHistory
            hist = MessageHistory(
                news_item_id=item.id,
                trigger_type=trigger_type,
                reason=reason,
                status="success"
            )
            db.add(hist)
            db.commit()
            log_event(db, "INFO", module_name, f"Successfully dispatched message for '{item.title[:40]}...' to {success_count} destinations.")
            return True
        except Exception as e:
            db.rollback()
            log_event(db, "ERROR", module_name, f"Error updating send status in DB: {e}")
            return True
            
    # Log failed history if no success
    try:
        from app.models import MessageHistory
        hist = MessageHistory(
            news_item_id=item.id,
            trigger_type=trigger_type,
            reason=reason,
            status="failed"
        )
        db.add(hist)
        db.commit()
    except Exception:
        pass
        
    return False

