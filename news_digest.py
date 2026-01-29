import os
import ssl
import smtplib
import time
from datetime import datetime
import pytz
import feedparser
from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =========================================================
# 1. THE SENSOR ARRAY (Global Market Intelligence)
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
    "https://news.google.com/rss/search?q=Titan+Tanishq+Kalyan+Malabar+Jewellers+expansion+GJEPC+policy&hl=en-IN&gl=IN&ceid=IN:en",
    
    # GLOBAL TRADE (FTA & Policy)
    "https://news.google.com/rss/search?q=India+EU+FTA+jewellery+zero+duty+impact&hl=en-IN&gl=IN&ceid=IN:en",
]

IST = pytz.timezone("Asia/Kolkata")

# =========================================================
# 2. THE BRAIN: AUTONOMOUS STRATEGIST
# =========================================================
def generate_strategic_directives(headlines_text: str) -> str:
    """The AI takes raw news and transforms it into C-Suite orders."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    current_date = datetime.now(IST).strftime("%B %d, %Y")
    
    # This prompt forces the AI to provide ACTION, not just news.
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

    response = client.chat.completions.create(
        model="gpt-4o", 
        messages=[{"role": "system", "content": prompt}],
        temperature=0.2 # Maintains clinical precision
    )
    return response.choices[0].message.content

# =========================================================
# 3. CORE LOGIC (Fetch & Process)
# =========================================================
def fetch_raw_intelligence() -> str:
    headlines = []
    seen = set()
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            if entry.link not in seen:
                headlines.append(f"Source: {feed.feed.get('title', 'Unknown')}\nTitle: {entry.title}\nLink: {entry.link}\n")
                seen.add(entry.link)
    return "\n".join(headlines)

def send_executive_briefing(content_html: str):
    msg = MIMEMultipart("alternative")
    today = datetime.now(IST).strftime("%d %b %Y")
    msg["Subject"] = f"👑 Sovereign Strategy Briefing | {today}"
    msg["From"] = os.environ.get("EMAIL_FROM")
    msg["To"] = os.environ.get("EMAIL_TO")
    
    # Custom Gold-Themed Styling for Boardroom Presence
    styled_html = f"""
    <html>
    <body style="font-family: 'Times New Roman', Times, serif; color: #1a1a1a; max-width: 850px; margin: auto; padding: 30px; border: 2px solid #C5A059;">
        <div style="text-align: center; border-bottom: 3px double #C5A059; padding-bottom: 10px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 28px; letter-spacing: 3px;">SOVEREIGN INTELLIGENCE</h1>
            <p style="color: #8C6A3B; font-style: italic; font-size: 14px;">End-to-End Strategic Directive for C-Suite Only</p>
        </div>
        {content_html}
        <div style="margin-top: 50px; font-size: 11px; color: #777; border-top: 1px solid #ddd; padding-top: 10px;">
            STRICTLY CONFIDENTIAL. This report is generated daily via the Sovereign-AI Hub. 
            Unauthorized circulation will compromise trade advantage.
        </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    with smtplib.SMTP(os.environ.get("SMTP_SERVER"), 587) as server:
        server.starttls()
        server.login(os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"))
        server.send_message(msg)

if __name__ == "__main__":
    print(f"[{datetime.now()}] Scanning global supply chain...")
    intel = fetch_raw_intelligence()
    
    print(f"[{datetime.now()}] Synthesizing multi-vertical strategy...")
    digest = generate_strategic_directives(intel)
    
    print(f"[{datetime.now()}] Dispatching to Boardroom...")
    send_executive_briefing(digest)
    
    print("Cycle complete. Market dominance maintained.")
