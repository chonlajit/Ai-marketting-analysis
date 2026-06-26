import json
import google.generativeai as genai
from sqlalchemy.orm import Session
from app.models import NewsItem, Setting
from app.database import log_event

def get_gemini_client(db: Session):
    """Retrieves API Key from DB or environment and configures genai."""
    api_key_setting = db.query(Setting).filter(Setting.key == "gemini_api_key").first()
    api_key = api_key_setting.value if api_key_setting else ""
    
    if not api_key:
        import os
        api_key = os.getenv("GEMINI_API_KEY", "")
        
    if not api_key:
        return None
        
    genai.configure(api_key=api_key)
    return genai

def get_model_name(db: Session) -> str:
    """Read the currently configured model name from settings (or env)."""
    setting = db.query(Setting).filter(Setting.key == "model_name").first()
    return setting.value if setting else "gemini-2.5-flash-lite"

def _update_rate_limit_status(db: Session, has_error: bool):
    """Updates the ai_rate_limit_error setting in DB."""
    setting = db.query(Setting).filter(Setting.key == "ai_rate_limit_error").first()
    status_str = "true" if has_error else "false"
    if not setting:
        setting = Setting(key="ai_rate_limit_error", value=status_str)
        db.add(setting)
    else:
        setting.value = status_str
    try:
        db.commit()
    except:
        db.rollback()

def filter_news(db: Session, item: NewsItem) -> bool:
    """
    Phase 1: Filter news using Gemini.
    Evaluates if headline is high impact for macroeconomic assets (USD, Gold, Nasdaq, SP500).
    Saves results to DB. Returns True if important, False otherwise.
    """
    module_name = "AI: Filter"
    
    # Forex Factory High Impact events are filtered in by default
    if item.is_calendar and item.calendar_details:
        impact = item.calendar_details.get("impact", "").lower()
        if impact == "high":
            item.is_important = True
            item.filter_reason = "Forex Factory High Impact Calendar Event"
            db.commit()
            return True
        elif impact in ["low", "medium"]:
            item.is_important = False
            item.filter_reason = f"Forex Factory {impact.capitalize()} Impact Event (Filtered Out)"
            db.commit()
            return False
            
    client = get_gemini_client(db)
    if not client:
        log_event(db, "ERROR", module_name, "Gemini API key is not configured.")
        return False
        
    try:
        # Prompt for filtering
        prompt = f"""
You are a financial intelligence filtering system named "Markus Anna". You have a polite, gentlemanly personality, and reply in a soft/gentle way.
Determine if the following financial news item has HIGH IMPORTANCE/HIGH IMPACT for global macroeconomic markets (specifically Gold, USD, Nasdaq, S&P 500).

High-importance news includes: FOMC/Fed decisions, CPI/PCE inflation, Non-Farm Payrolls (NFP)/Employment reports, GDP announcements, wars/geopolitical conflicts, banking system crises, major energy supply disruptions, or actions by major central banks (ECB, BOJ, Fed).
Low-importance/Noise news includes: corporate earnings of single companies (e.g. Apple launching a color, TSMC minor reports), daily regular stock market reports, opinion pieces, or minor technical analyst comments.

News Title: {item.title}
News Source: {item.source}
News Content/Summary: {item.raw_content}

Return a JSON object in this exact format:
{{
  "is_important": true/false,
  "importance_percent": 75,
  "gold_impact": "สูง/ปานกลาง/ต่ำ",
  "reason": "สรุปเหตุผลเป็นภาษาไทยสั้นๆ ที่มีน้ำเสียงสุภาพ นุ่มนวล แบบสุภาพบุรุษ ลงท้ายด้วย 'ครับ' หรือ 'ครับผม' (ไม่เกิน 1 บรรทัด)"
}}

หมายเหตุ: importance_percent คือระดับความสำคัญของข่าวนี้ต่อตลาดการเงินโลก 0-100% (100% = สำคัญมากที่สุด) และ gold_impact คือระดับผลกระทบต่อราคาทองคำ
"""
        
        # Configure model
        model = client.GenerativeModel(
            model_name=get_model_name(db),
            generation_config={"response_mime_type": "application/json"}
        )
        
        response = model.generate_content(prompt)
        result = json.loads(response.text)
        
        item.is_important = result.get("is_important", False)
        item.filter_reason = result.get("reason", "No reason provided.")
        # Store extra filter metadata in a dedicated field if available, else embed in filter_reason
        item.importance_percent = result.get("importance_percent", None)
        item.gold_impact_level = result.get("gold_impact", None)
        db.commit()
        
        status_str = "IMPORTANT" if item.is_important else "NOISE"
        log_event(db, "INFO", module_name, f"Processed '{item.title[:40]}...'. Result: {status_str}. Importance: {result.get('importance_percent', '?')}%. Gold: {result.get('gold_impact', '?')}. Reason: {item.filter_reason}")
        _update_rate_limit_status(db, False)
        return item.is_important
        
    except Exception as e:
        db.rollback()
        error_msg = str(e)
        log_event(db, "ERROR", module_name, f"Error filtering news '{item.title[:40]}...': {error_msg}")
        if "429" in error_msg or "quota" in error_msg.lower():
            _update_rate_limit_status(db, True)
            
        # In case of API issues, default to False to avoid spamming alerts
        item.is_important = False
        item.filter_reason = f"Error during filter: {error_msg}"
        db.commit()
        return False

def analyze_news(db: Session, item: NewsItem) -> bool:
    """
    Phase 2: Deep Analysis and Scoring using Gemini.
    Generates impact directions (+, -, 0) for USD, Gold, Nasdaq, SP500, Thai summary, and confidence.
    """
    module_name = "AI: Analysis"
    client = get_gemini_client(db)
    if not client:
        log_event(db, "ERROR", module_name, "Gemini API key is not configured.")
        return False
        
    try:
        # Prompt for analysis
        prompt = f"""
You are a senior financial intelligence analyst named "Markus Anna". You have a polite, gentlemanly personality, and reply in a soft/gentle way.
Perform a deep analysis of the following macroeconomic news and its direct impact on:
1. Gold (ทองคำ)
2. USD (ดอลลาร์สหรัฐ)
3. Nasdaq (ดัชนีแนสแด็ก)
4. S&P 500 (ดัชนีเอสแอนด์พี 500)

Analyze:
- The direction of impact for each asset: "+" (Positive/Bullish), "-" (Negative/Bearish), or "0" (Neutral).
- A short Thai explanation (reason) for each asset's impact. Use a polite, gentle, and gentlemanly tone in Thai (ending with ครับ/ครับผม/ขอรับ/ครับท่าน).
- An overall importance score (1-10).
- Confidence level (0-100%).
- A concise Thai summary strictly containing:
  1. "what_happened": เหตุการณ์คืออะไร (What happened - max 1 sentence, explain in a polite, gentle gentlemanly tone in Thai ending with ครับ/ครับผม)
  2. "what_it_affects": ส่งผลต่ออะไร (What it affects - max 1 sentence, explain in a polite, gentle gentlemanly tone in Thai ending with ครับ/ครับผม)
  3. "what_to_watch_next": ควรจับตาอะไรต่อ (What to watch next - max 1 sentence, explain in a polite, gentle gentlemanly tone in Thai ending with ครับ/ครับผม)
- The step-by-step reasoning chain (ขั้นตอนการวิเคราะห์เชิงเหตุและผล) in Thai (e.g. 'เงินเฟ้อสูง -> Fed ขึ้นดอกเบี้ย -> USD แข็งค่า -> ทองถูกกดดัน').

CRITICAL INSTRUCTION FOR CALENDAR EVENTS: 
If the news is a Calendar Event (e.g. Impact: High, Forecast: X, Previous: Y), you MUST analyze it as a Scenario Analysis based on the Forecast. 
Assume the actual result will meet or exceed the Forecast. 
ALWAYS assign an importance_score of 8 to 10 for High Impact calendar events, and assign a HIGH confidence_score (e.g., 85-95%) because these are major macroeconomic indicators. Do NOT assign low scores just because the actual result is not out yet.

News Title: {item.title}
News Source: {item.source}
News Content/Summary: {item.raw_content}

Return a JSON object in this exact format:
{{
  "importance_score": 9,
  "confidence_score": 92,
  "assets": {{
    "USD": {{"impact": "+", "reason": "อธิบายผลกระทบดอลลาร์สหรัฐภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม"}},
    "Gold": {{"impact": "-", "reason": "อธิบายผลกระทบทองคำภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม"}},
    "Nasdaq": {{"impact": "-", "reason": "อธิบายผลกระทบแนสแด็กภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม"}},
    "SP500": {{"impact": "-", "reason": "อธิบายผลกระทบเอสแอนด์พี 500ภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม"}}
  }},
  "summary": {{
    "what_happened": "สรุปเหตุการณ์ภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม",
    "what_it_affects": "อธิบายผลกระทบภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม",
    "what_to_watch_next": "สิ่งที่ควรติดตามต่อภาษาไทยแบบสุภาพนุ่มนวลลงท้ายด้วย ครับ หรือ ครับผม"
  }},
  "reasoning_chain": "เงินเฟ้อสูง -> Fed มีแนวโน้มขึ้นดอกเบี้ย -> USD แข็งค่า -> ทองถูกกดดัน"
}}
"""
        
        # Configure model
        model = client.GenerativeModel(
            model_name=get_model_name(db),
            generation_config={"response_mime_type": "application/json"}
        )
        
        response = model.generate_content(prompt)
        result = json.loads(response.text)
        
        # Save analysis to database
        item.ai_analysis = result
        db.commit()
        
        log_event(db, "INFO", module_name, f"Successfully analyzed item '{item.title[:40]}...'. Importance: {result.get('importance_score')}/10, Confidence: {result.get('confidence_score')}%")
        _update_rate_limit_status(db, False)
        return True
        
    except Exception as e:
        db.rollback()
        error_msg = str(e)
        log_event(db, "ERROR", module_name, f"Error analyzing news '{item.title[:40]}...': {error_msg}")
        if "429" in error_msg or "quota" in error_msg.lower():
            _update_rate_limit_status(db, True)
        return False
