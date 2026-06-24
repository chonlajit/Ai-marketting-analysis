import httpx
import feedparser
import xml.etree.ElementTree as ET
from datetime import datetime
import hashlib
from sqlalchemy.orm import Session
from app.models import NewsItem, FeedConfig
from app.database import log_event

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def clean_html(raw_html):
    """Simple helper to strip HTML tags if present."""
    if not raw_html:
        return ""
    import re
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def fetch_rss_feed(db: Session, feed: FeedConfig) -> int:
    """Parses a standard RSS news feed (Yahoo Finance, CNBC, MarketWatch)."""
    module_name = "Fetcher: RSS"
    new_items_count = 0
    
    try:
        log_event(db, "INFO", module_name, f"Fetching feed: {feed.name} from {feed.url}")
        
        # Use httpx to download content to avoid feedparser timeouts or blocks
        with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            response = client.get(feed.url)
            response.raise_for_status()
            feed_data = feedparser.parse(response.text)
            
        if not feed_data.entries:
            log_event(db, "WARNING", module_name, f"No entries found in feed: {feed.name}")
            return 0

        for entry in feed_data.entries:
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            
            if not title or not url:
                continue

            # Check if already exists in DB
            exists = db.query(NewsItem).filter(NewsItem.url == url).first()
            if exists:
                continue

            # Parse published date
            published_at = datetime.utcnow()
            for date_field in ["published_parsed", "updated_parsed", "created_parsed"]:
                parsed_time = entry.get(date_field)
                if parsed_time:
                    try:
                        published_at = datetime(*parsed_time[:6])
                        break
                    except Exception:
                        pass
            
            summary = clean_html(entry.get("summary", entry.get("description", "")))
            
            # Save news item
            news_item = NewsItem(
                title=title,
                source=feed.name,
                url=url,
                published_at=published_at,
                raw_content=summary,
                tier=feed.tier,
                is_calendar=False,
                is_important=None,  # Pending AI review
                telegram_sent=False
            )
            db.add(news_item)
            new_items_count += 1

        db.commit()
        log_event(db, "INFO", module_name, f"Successfully parsed {feed.name}. Added {new_items_count} new articles.")
        return new_items_count
        
    except Exception as e:
        db.rollback()
        log_event(db, "ERROR", module_name, f"Error fetching feed {feed.name}: {str(e)}")
        return 0

def fetch_forex_calendar(db: Session, feed: FeedConfig) -> int:
    """Parses Forex Factory Weekly XML Calendar Feed."""
    module_name = "Fetcher: Calendar"
    new_events_count = 0
    
    try:
        log_event(db, "INFO", module_name, f"Fetching calendar: {feed.name} from {feed.url}")
        
        with httpx.Client(headers=HEADERS, timeout=15.0) as client:
            response = client.get(feed.url)
            response.raise_for_status()
            
        xml_content = response.content
        root = ET.fromstring(xml_content)
        
        events = root.findall("event")
        if not events:
            log_event(db, "WARNING", module_name, f"No events found in Forex Factory XML.")
            return 0
            
        for event in events:
            title = event.find("title").text if event.find("title") is not None else ""
            country = event.find("country").text if event.find("country") is not None else ""
            date_str = event.find("date").text if event.find("date") is not None else ""
            time_str = event.find("time").text if event.find("time") is not None else ""
            impact = event.find("impact").text if event.find("impact") is not None else ""
            forecast = event.find("forecast").text if event.find("forecast") is not None else ""
            previous = event.find("previous").text if event.find("previous") is not None else ""
            
            if not title or not country or not date_str:
                continue
                
            # Create a unique virtual URL/GUID based on event signature to prevent duplication
            sig = f"{title}_{country}_{date_str}_{time_str}".encode("utf-8")
            url = f"https://www.forexfactory.com/calendar#event_{hashlib.md5(sig).hexdigest()}"
            
            # Check if exists
            exists = db.query(NewsItem).filter(NewsItem.url == url).first()
            if exists:
                # Update forecast/previous/actual if they changed (in case numbers get updated)
                calendar_details = {
                    "country": country,
                    "impact": impact,
                    "forecast": forecast,
                    "previous": previous,
                    "event_time": time_str
                }
                if exists.calendar_details != calendar_details:
                    exists.calendar_details = calendar_details
                    db.commit()
                continue
                
            # Parse event date and time
            # Date format: 06-25-2026, Time format: 07:30pm (or All Day / Tentative)
            event_datetime = datetime.utcnow()
            try:
                if time_str and time_str.lower() not in ["all day", "tentative"]:
                    event_datetime = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
                else:
                    event_datetime = datetime.strptime(date_str, "%m-%d-%Y")
            except Exception:
                try:
                    event_datetime = datetime.strptime(date_str, "%m-%d-%Y")
                except Exception:
                    pass
            
            calendar_details = {
                "country": country,
                "impact": impact,
                "forecast": forecast,
                "previous": previous,
                "event_time": time_str
            }
            
            # Format high-level description for the AI
            raw_content = f"Country: {country} | Event: {title} | Impact: {impact} | Forecast: {forecast} | Previous: {previous}"
            
            # Calendar event news item
            # For Forex Factory: High Impact events are ALWAYS considered important
            is_important = True if impact.lower() == "high" else None
            
            news_item = NewsItem(
                title=f"[{country}] {title}",
                source="Forex Factory Calendar",
                url=url,
                published_at=event_datetime,
                raw_content=raw_content,
                tier=feed.tier,
                is_calendar=True,
                calendar_details=calendar_details,
                is_important=is_important,
                telegram_sent=False
            )
            db.add(news_item)
            new_events_count += 1
            
        db.commit()
        log_event(db, "INFO", module_name, f"Successfully parsed calendar. Added {new_events_count} new events.")
        return new_events_count
        
    except Exception as e:
        db.rollback()
        log_event(db, "ERROR", module_name, f"Error fetching calendar: {str(e)}")
        return 0

def fetch_all(db: Session) -> dict:
    """Fetches all active news feeds and calendars."""
    feeds = db.query(FeedConfig).filter(FeedConfig.active == True).all()
    results = {}
    total_added = 0
    
    for feed in feeds:
        if feed.is_calendar:
            added = fetch_forex_calendar(db, feed)
        else:
            added = fetch_rss_feed(db, feed)
        results[feed.name] = added
        total_added += added
        
    return {"feeds_processed": len(feeds), "added_count": total_added, "breakdown": results}
