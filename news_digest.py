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
# 1. ENHANCED CONFIG & BRAND TRACKING
# =========================================================

# Focus Brands for specific monitoring
TARGET_BRANDS = [
    "Titan", "Tanishq", "Kalyan Jewellers", "Malabar Gold", "Kisna", 
    "PC Jeweller", "PNG Jewellers", "Palmonas", "CaratLane", "BlueStone",
    "LVMH", "Tiffany", "Cartier", "Bulgari", "Richemont"
]

RSS_FEEDS = [
    # Global Luxury & Industry Authority
    "https://www.jckonline.com/feed/",
    "https://www.nationaljeweller.com/rss",
    "https://www.professionaljeweller.com/feed/",
    "https://www.voguebusiness.com/feed/companies/jewellery",
    "https://www.gold.org/rss/news",
    
    # specialized Indian Industry
    "https://www.solitaireinternational.com/feed/",
    "https://gjepc.org/news_rss.php",
    
    # Brand Specific Google News Tracking (Dynamic)
    "https://news.google.com/rss/search?q=Titan+Company+Tanishq+jewellery+news&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Kalyan+Jewellers+Malabar+Gold+industry&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Palmonas+GIVA+demi-fine+jewellery&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=LVMH+Tiffany+Richemont+strategy+jewellery&hl=en-US&gl=US&ceid=US:en",
]

MAX_ITEMS_PER_FEED = 10
MAX_TOTAL_ITEMS = 40  
IST = pytz.timezone("Asia/Kolkata")

# =========================================================
# 2. INTELLIGENT FETCHING
# =========================-================================

def is_recent(entry) -> bool:
    now = datetime.now(IST)
    dt = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)
    if not dt: return False
    return (now - dt) <= timedelta(hours=36) # Increased window slightly for global news

def fetch_news() -> List[Dict]:
    items = []
    seen = set()
    idx = 1

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get("title", "Industry Report")
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        for e in entries:
            if not is_recent(e): continue
            
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link or title.lower() in seen: continue
            
            # Brand Prioritization Logic
            priority = 0
            for brand in TARGET_BRANDS:
                if brand.lower() in title.lower():
                    priority = 1
                    break

            items.append({
                "id": idx,
                "source": source,
                "title": title,
                "link": link,
                "priority": priority
            })
            seen.add(title.lower())
            idx += 1

    # Sort by priority so AI sees target brands first
    return sorted(items, key=lambda x: x['priority'], reverse=True)[:MAX_TOTAL_ITEMS]

def build_headlines_text(items: List[Dict]) -> str:
    return "\n".join([f"{' [PRIORITY]' if i['priority'] else ''} {i['source']}: {i['title']}" for i in items])

# =========================================================
# 3. THE CEO-STRATEGIST PROMPT (GPT-4o)
# =========================================================

def ask_ai_for_digest(headlines_text: str, items: List[Dict]) -> str:
    client = OpenAI()
    today = datetime.now(IST).strftime("%B %d, %Y")
    
    # Extract titles for the context
    editorial_sample = items[0]['title'] if items else "Market Volatility"

    prompt = f"""
You are the Chief Strategy Officer for a multi-billion dollar jewellery conglomerate. 
Your audience is the CEO and the Board of Directors. 

Date: {today}
Context: India is the primary profit engine; Global Luxury (LVMH/Richemont) is the benchmark for strategy.

INPUT HEADLINES:
{headlines_text}

TASK: Generate a "Premium Intelligence Briefing."
STYLE: High-stakes, analytical, sharp, and predictive. No fluff. Use HTML for structure.

MANDATORY SECTIONS:

1. <h2 style="color: #b8860b;">💎 The Billion-Dollar Brand Pulse</h2>
Analyze news regarding Titan, Kalyan, Malabar, and Global Luxury players. 
How are they shifting their store footprints, marketing, or inventory? 

2. <h2 style="color: #2c3e50;">🌍 Macro & Hedging Strategy</h2>
Gold/Silver price movements vs. interest rate projections. 
Impact on the Indian "Making Charge" competitive landscape.

3. <h2 style="color: #2c3e50;">📦 The Sourcing & Procurement Edge</h2>
Compare manufacturing logic:
- **Mass Scale:** Casting vs. Machine-made (Titan/Kalyan strategy).
- **Heritage:** Nakashi, Kundan, and Filigree (Why hand-made justifies a 25% premium).
- **Modern:** Demi-fine (Palmonas/GIVA) and Lab-Grown (Limelight). How should a CEO balance inventory between 22k Gold and LGD?

4. <h2 style="color: #2c3e50;">📉 What is 'Stuck' vs 'Flowing'</h2>
Predict based on current sentiment: Are consumers buying heavy bridal or moving to lightweight 'everyday luxury'?

5. <h2 style="color: #c0392b;">🎯 Strategic Command</h2>
Ask one hard question about the business model (e.g., "Is our reliance on franchised showrooms a liability in a high-interest environment?") and provide the CEO-level answer.

6. <h2 style="color: #2c3e50;">🔗 Top 3 Must-Read Sources</h2>
List 3 most critical links from the headlines provided with 1-sentence logic why they are mandatory.
"""

    response = client.chat.completions.create(
        model="gpt-4o", # Using GPT-4o for higher reasoning
        messages=[{"role": "system", "content": "You are a professional luxury industry consultant."},
                  {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2500
    )

    return response.choices[0].message.content

# =========================================================
# 4. EMAIL & EXECUTION
# =========================================================

def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject

    # Add some basic CSS for a premium look
    styled_html = f"""
    <html>
        <body style="font-family: 'Georgia', serif; line-height: 1.6; color: #333; max-width: 800px; margin: auto; padding: 20px; border: 1px solid #eee;">
            <div style="text-align: center; border-bottom: 2px solid #b8860b; padding-bottom: 10px; margin-bottom: 20px;">
                <h1 style="color: #b8860b; margin-bottom: 0;">JEWELLERY EXECUTIVE INTELLIGENCE</h1>
                <p style="text-transform: uppercase; letter-spacing: 2px; font-size: 12px;">Confidential Strategy Briefing</p>
            </div>
            {html}
            <div style="margin-top: 40px; font-size: 10px; color: #999; text-align: center; border-top: 1px solid #eee; padding-top: 20px;">
                Generated by Gemini Intelligence Labs for Private Circulation.
            </div>
        </body>
    </html>
    """
    msg.attach(MIMEText(styled_html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls(context=context)
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)

def main():
    print("Fetching industry intelligence...")
    news = fetch_news()
    if not news:
        print("No material news found.")
        return

    print(f"Analyzing {len(news)} reports...")
    digest = ask_ai_for_digest(build_headlines_text(news), news)

    subject = f"💎 CEO Intelligence: {datetime.now(IST).strftime('%d %b %Y')} | Market Strategy"
    send_email(subject, digest)
    print("Strategic digest sent successfully.")

if __name__ == "__main__":
    main()
