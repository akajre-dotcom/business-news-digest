import os
import ssl
import smtplib
import time
from datetime import datetime, timedelta
from typing import List, Dict

import feedparser
import pytz
from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =========================================================
# 1. THE SENSOR ARRAY (Global Intelligence Sources)
# =========================================================
RSS_FEEDS = [
    # BULLION & MACRO (Price Discovery & Interest Rates)
    "https://www.gold.org/rss/news", 
    "https://news.google.com/rss/search?q=LBMA+gold+price+forecast+inflation+macroeconomics&hl=en-IN&gl=IN&ceid=IN:en",
    
    # DIAMONDS & GEMS (Natural vs LGD Sourcing)
    "https://rapaport.com/feed/",
    "https://news.google.com/rss/search?q=De+Beers+Alrosa+diamond+supply+chain+lab+grown+pricing&hl=en-IN&gl=IN&ceid=IN:en",
    
    # RETAIL & COMPETITION (India/GCC Dynamics)
    "https://www.solitaireinternational.com/feed/",
    "https://news.google.com/rss/search?q=Titan+Tanishq+Kalyan+Malabar+Jewellers+strategy&hl=en-IN&gl=IN&ceid=IN:en",
    
    # GLOBAL TRADE (FTA & Policy)
    "https://news.google.com/rss/search?q=India+EU+FTA+jewellery+zero+duty+impact&hl=en-IN&gl=IN&ceid=IN:en",
]

IST = pytz.timezone("Asia/Kolkata")
MAX_ITEMS_PER_FEED = 15

# =========================================================
# 2. DATA HARVESTING
# =========================================================
def is_recent(entry) -> bool:
    now = datetime.now(IST)
    dt = None
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        dt = datetime.fromtimestamp(time.mktime(parsed), IST)
    return dt and (now - dt) <= timedelta(hours=24)

def fetch_news() -> str:
    headlines = []
    seen = set()
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        # Use recent news; fallback to last 3 entries if none are from last 24h
        recent = [e for e in feed.entries if is_recent(e)]
        use_entries = recent if recent else feed.entries[:3]
        
        for e in use_entries:
            link = e.get("link")
            if link not in seen:
                headlines.append(f"Source: {feed.feed.get('title', 'Market')}\nTitle: {e.title}\nLink: {link}\n")
                seen.add(link)
    return "\n".join(headlines)

# =========================================================
# 3. THE BRAIN: AUTONOMOUS STRATEGIST
# =========================================================
def generate_strategic_directives(headlines_text: str) -> str:
    """Transforms raw news into C-Suite orders using 2026 Responses API."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    current_date = datetime.now(IST).strftime("%B %d, %Y")
    
    prompt = f"""
    You are a Strategic Consultant paid $1B for industry dominance. 
    Today's Date: {current_date}. 
    Analyze these headlines for a global jewellery conglomerate (Cartier/Titan/Kalyan grade).

    HEADLINES:
    {headlines_text}

    OUTPUT RULES:
    - Structure: Pure HTML. 
    - Tone: Blunt, authoritative, C-Suite directive.
    - Logic: Use [SIGNAL] -> [IMPACT] -> [COMMAND].
    - Vertical Focus: Cover the entire flow from Mine-to-Showroom (End-to-End).

    SECTIONS TO COVER:
    1. 🏛️ CEO LEVEL: Macro pivots (FTAs, Trade Wars, M&A).
    2. 💰 CFO LEVEL: Bullion hedging, Currency risk, GML (Gold Metal Loans).
    3. 💎 PROCUREMENT: Natural vs LGD sourcing strategy, BIS standards.
    4. 📦 MERCHANDISING: Inventory turnover (GMROI), Category shifts (14K vs 22K).
    5. 📈 SALES: Consumer psychology, converting 'Sticker Shock' into 'Investment Value'.
    
    6. ⚠️ THE BLACK SWAN: One high-probability risk the market is ignoring.
    """

    # Using the 2026 stable Responses API for autonomous agents
    response = client.responses.create(
        model="gpt-5", # Model fallback to gpt-4o if not available
        input=prompt,
        temperature=0.1
    )
    return response.output[0].text.strip()

# =========================================================
# 4. EMAIL DISPATCH
# =========================================================
def send_email(html_body: str):
    msg = MIMEMultipart("alternative")
    today = datetime.now(IST).strftime("%d %b %Y")
    msg["Subject"] = f"👑 Sovereign Intelligence Briefing | {today}"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    
    styled_html = f"""
    <div style="font-family: 'Times New Roman', serif; color: #1a1a1a; padding: 25px; border: 3px double #C5A059; max-width: 900px; margin: auto;">
        <h1 style="text-align: center; color: #8C6A3B; letter-spacing: 2px; border-bottom: 1px solid #C5A059;">SOVEREIGN STRATEGY</h1>
        {html_body}
        <hr style="border: 0; border-top: 1px solid #eee; margin-top: 40px;">
        <p style="font-size: 11px; color: #999;">CONFIDENTIAL. Generated via Autonomous Sovereign Hub.</p>
    </div>
    """
    msg.attach(MIMEText(styled_html, "html"))

    with smtplib.SMTP(os.environ["SMTP_SERVER"], 587) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.send_message(msg)

# =========================================================
# 5. EXECUTION
# =========================================================
if __name__ == "__main__":
    try:
        intel = fetch_news()
        if intel:
            digest = generate_strategic_directives(intel)
            send_email(digest)
            print("Intelligence dispatched successfully.")
        else:
            print("No new signals today.")
    except Exception as e:
        print(f"Deployment Error: {e}")
        exit(1)
