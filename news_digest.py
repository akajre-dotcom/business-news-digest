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
from email.utils import make_msgid   # ✅ added

# =========================================================
# 1. ENHANCED CONFIG & BRAND TRACKING
# =========================================================

TARGET_BRANDS = [
    "Tanishq", "Titan", "Kalyan Jewellers", "Malabar Gold & Diamonds", 
    "Joyalukkas", "PC Jeweller", "Reliance Jewels", "Senco Gold & Diamonds", 
    "GRT Jewellers", "Bhima", "Khazana", "Lalitha Jewellery", 
    "Vummidi Bangaru", "VBJ", "Prince", "Thangamayil", "Jos Alukkas", 
    "Tribhovandas Bhimji Zaveri", "TBZ", "P.N. Gadgil", "PNG", 
    "Waman Hari Pethe", "WHP", "Chandukaka Saraf", "Chintamani's", 
    "P.C. Chandra Jewellers", "Anjali Jewellers", "Sawansukha", 
    "Chandrani Pearls", "Khanna Jewellers", "Mehra Brothers", "Liali", 
    "Punjab Jewellers", "Zoya", "Hazoorilal Legacy", "Sabyasachi Fine Jewellery", 
    "C. Krishniah Chetty", "CKC", "Amrapali Jewels", "Birdhichand Ghanshyamdas", 
    "Kantilal Chhotalal", "CaratLane", "BlueStone", "Mia by Tanishq", 
    "Melorra", "GIVA", "Palmonas", "Limelight Diamonds", "Jewelbox", 
    "Fiona Diamonds", "Avtaara", "Ivana", "Kushal’s Fashion Jewellery", 
    "Rubans", "Isharya", "Outhouse", "Zaveri Pearls", "Salty"
]

RSS_FEEDS = [
    "https://www.jckonline.com/feed/",
    "https://www.nationaljeweller.com/rss",
    "https://www.professionaljeweller.com/feed/",
    "https://www.voguebusiness.com/feed/companies/jewellery",
    "https://www.gold.org/rss/news",
    "https://www.solitaireinternational.com/feed/",
    "https://gjepc.org/news_rss.php",
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
# =========================================================

def is_recent(entry) -> bool:
    now = datetime.now(IST)
    dt = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)
    if not dt:
        return False
    return (now - dt) <= timedelta(hours=36)

def fetch_news() -> List[Dict]:
    items = []
    seen = set()
    idx = 1

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get("title", "Industry Report")
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        for e in entries:
            if not is_recent(e):
                continue

            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link or title.lower() in seen:
                continue

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

    return sorted(items, key=lambda x: x["priority"], reverse=True)[:MAX_TOTAL_ITEMS]

def build_headlines_text(items: List[Dict]) -> str:
    return "\n".join(
        [f"{' [PRIORITY]' if i['priority'] else ''} {i['source']}: {i['title']}" for i in items]
    )

# =========================================================
# 3. AI DIGEST (UNCHANGED)
# =========================================================

def ask_ai_for_digest(headlines_text: str, items: List[Dict]) -> str:
    client = OpenAI()
    today = datetime.now(IST).strftime("%B %d, %Y")

    prompt = f"""
You are the Chief Strategy Officer for a multi-billion dollar jewellery conglomerate.
Your audience is the CEO and the Board of Directors.

Date: {today}

INPUT HEADLINES:
{headlines_text}

Generate a premium intelligence briefing in HTML.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional luxury industry consultant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2500,
    )

    return response.choices[0].message.content

# =========================================================
# 4. EMAIL (ONLY FIXED PART)
# =========================================================

def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()   # ✅ added

    # ✅ REQUIRED PLAIN-TEXT PART (CRITICAL)
    text_fallback = (
        "Jewellery Executive Intelligence\n\n"
        "This briefing is designed for HTML-capable email clients."
    )

    msg.attach(MIMEText(text_fallback, "plain"))

    styled_html = f"""
    <html>
        <body style="font-family: 'Georgia', serif; line-height: 1.6; color: #333; max-width: 800px; margin: auto; padding: 20px; border: 1px solid #eee;">
            <div style="text-align: center; border-bottom: 2px solid #b8860b; padding-bottom: 10px; margin-bottom: 20px;">
                <h1 style="color: #b8860b; margin-bottom: 0;">JEWELLERY EXECUTIVE INTELLIGENCE</h1>
                <p style="text-transform: uppercase; letter-spacing: 2px; font-size: 12px;">Confidential Strategy Briefing</p>
            </div>
            {html}
            <div style="margin-top: 40px; font-size: 10px; color: #999; text-align: center; border-top: 1px solid #eee; padding-top: 20px;">
                Generated for Private Circulation.
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

# =========================================================
# 5. MAIN
# =========================================================

def main():
    print("Fetching industry intelligence...")
    news = fetch_news()
    if not news:
        print("No material news found.")
        return

    print(f"Analyzing {len(news)} reports...")
    digest = ask_ai_for_digest(build_headlines_text(news), news)

    # ❌ emoji removed from SUBJECT ONLY
    subject = f"CEO Intelligence | {datetime.now(IST).strftime('%d %b %Y')} | Market Strategy"
    send_email(subject, digest)
    print("Strategic digest sent successfully.")

if __name__ == "__main__":
    main()
