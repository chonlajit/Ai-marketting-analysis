import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import NewsItem, Setting
from app.database import log_event

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
        return f"🚨 <b>NEWS REPORT:</b>\n{item.title}\n\n{item.raw_content}\n\n<a href='{item.url}'>Read full article</a>"
        
    importance = analysis.get("importance_score", 5)
    confidence = analysis.get("confidence_score", 50)
    assets = analysis.get("assets", {})
    summary = analysis.get("summary", {})
    reasoning = analysis.get("reasoning_chain", "")
    
    # Header logic based on importance score
    if importance >= 8:
        header = "🚨 <b>HIGH IMPACT NEWS (ด่วนที่สุด)</b>"
    elif importance >= 5:
        header = "⚠️ <b>MODERATE IMPACT NEWS (ข่าวสำคัญ)</b>"
    else:
        header = "📊 <b>FINANCIAL NEWS (ข่าวทั่วไป)</b>"
        
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
    
    # Build text
    msg = f"{header}\n"
    msg += f"📰 <b>{item.title}</b>\n"
    msg += f"📍 แหล่งที่มา: {item.source}\n\n"
    
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
    msg += f"🔹 <b>เหตุการณ์:</b> {summary.get('what_happened', '-')}\n"
    msg += f"🔹 <b>ส่งผลต่อ:</b> {summary.get('what_it_affects', '-')}\n"
    msg += f"🔹 <b>สิ่งที่ต้องจับตา:</b> {summary.get('what_to_watch_next', '-')}\n\n"
    
    if reasoning:
        msg += "🧠 <b>ขั้นตอนวิเคราะห์ (Reasoning Chain):</b>\n"
        msg += f"<code>{reasoning}</code>\n\n"
        
    msg += f"🎯 ความมั่นใจ: <b>{confidence}%</b> | คะแนนความสำคัญ: <b>{importance}/10</b>\n"
    msg += f"🔗 <a href='{item.url}'>อ่านข่าวต้นฉบับ (Full Article)</a>"
    
    return msg

def send_to_telegram(db: Session, item: NewsItem) -> bool:
    """Sends formatted HTML report to the configured Telegram channel/group."""
    module_name = "Telegram Publisher"
    bot_token, chat_id = get_telegram_credentials(db)
    
    if not bot_token or not chat_id:
        log_event(db, "ERROR", module_name, "Telegram Bot Token or Chat ID is not configured.")
        return False
        
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        text = format_telegram_message(item)
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            
        # Update database status
        item.telegram_sent = True
        item.telegram_sent_at = datetime.utcnow()
        db.commit()
        
        log_event(db, "INFO", module_name, f"Successfully dispatched message for '{item.title[:40]}...' to Telegram.")
        return True
        
    except Exception as e:
        db.rollback()
        log_event(db, "ERROR", module_name, f"Error sending message to Telegram: {str(e)}")
        return False
