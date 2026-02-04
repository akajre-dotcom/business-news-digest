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
# 1. CONFIG
# =========================================================

# =========================================================
# MASTER RSS FEEDS – GLOBAL TRADE (INDIA-RELEVANT)
# =========================================================

RSS_FEEDS = [

    # -----------------------------------------------------
    # 1. GLOBAL & TRADE AUTHORITIES (PRICE + PIPELINE)
    # -----------------------------------------------------
    "https://www.gold.org/rss/news",              # Global gold flows, policy
    "https://rapaport.com/feed/",                 # Diamond pricing & sentiment
    "https://www.solitaireinternational.com/feed/",  # India + global diamond trade

    # -----------------------------------------------------
    # 2. INDIA JEWELLERY MARKET – MASTER SIGNAL
    # (Catches ALL brands, regions, family jewellers)
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=India+jewellery+market&hl=en-IN&gl=IN&ceid=IN:en",

    # -----------------------------------------------------
    # 3. CORPORATE, POLICY & REGULATORY EVENTS
    # (IPO, GST, raids, compliance, funding)
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=jewellery+company+India+policy&hl=en-IN&gl=IN&ceid=IN:en",

    # -----------------------------------------------------
    # 4. RETAIL & STORE EXPANSION / CONSOLIDATION
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=jewellery+retail+store+India&hl=en-IN&gl=IN&ceid=IN:en",

    # -----------------------------------------------------
    # 5. MANUFACTURING, CRAFT & SOURCING (LEARNING ENGINE)
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=jewellery+manufacturing+India+craft&hl=en-IN&gl=IN&ceid=IN:en",

    # -----------------------------------------------------
    # 6. PRODUCT, DESIGN & HANDMADE LANGUAGE
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=handmade+gold+jewellery+India+design&hl=en-IN&gl=IN&ceid=IN:en",

    # -----------------------------------------------------
    # 7. DIAMONDS, POLKI, LGD (FULL PIPELINE)
    # -----------------------------------------------------
    "https://news.google.com/rss/search?q=diamond+polki+lab+grown+jewellery+India&hl=en-IN&gl=IN&ceid=IN:en",
]

# ---------------------------------------------------------
# SAFETY LIMITS (KEEP AS-IS)
# ---------------------------------------------------------
MAX_ITEMS_PER_FEED = 8
MAX_TOTAL_ITEMS = 30
IST = pytz.timezone("Asia/Kolkata")

# =========================================================
# 2. TARGET BRAND KEYWORDS (NEWS MATCHING ONLY)
# =========================================================

TARGET_BRANDS = {
    "Tanishq": ["tanishq"],
    "Titan": ["titan"],
    "Kalyan Jewellers": ["kalyan jewellers", "kalyan jewellery"],
    "Malabar Gold & Diamonds": ["malabar gold", "malabar jewellery"],
    "Joyalukkas": ["joyalukkas"],
    "PC Jeweller": ["pc jeweller", "pcjeweller"],
    "Reliance Jewels": ["reliance jewels"],
    "Senco Gold & Diamonds": ["senco gold", "senco jewellery"],
    "GRT Jewellers": ["grt jewellers", "grt"],
    "Bhima": ["bhima jewellers", "bhima gold"],
    "Khazana": ["khazana jewellery"],
    "Lalitha Jewellery": ["lalitha jewellery"],
    "Vummidi Bangaru": ["vummidi bangaru", "vbj"],
    "Prince": ["prince jewellers"],
    "Thangamayil": ["thangamayil"],
    "Jos Alukkas": ["jos alukkas"],
    "Tribhovandas Bhimji Zaveri": ["tribhovandas bhimji zaveri", "tbz"],
    "P.N. Gadgil": ["p.n. gadgil", "pn gadgil", "png jewellers"],
    "Waman Hari Pethe": ["waman hari pethe", "whp"],
    "Chandukaka Saraf": ["chandukaka saraf"],
    "Chintamani's": ["chintamani jewellers"],
    "P.C. Chandra Jewellers": ["pc chandra jewellers"],
    "Anjali Jewellers": ["anjali jewellers"],
    "Sawansukha": ["sawansukha jewellers"],
    "Chandrani Pearls": ["chandrani pearls"],
    "Khanna Jewellers": ["khanna jewellers"],
    "Mehra Brothers": ["mehra brothers"],
    "Liali": ["liali jewellery"],
    "Punjab Jewellers": ["punjab jewellers"],
    "Zoya": ["zoya jewellery"],
    "Hazoorilal Legacy": ["hazoorilal"],
    "Sabyasachi Fine Jewellery": ["sabyasachi jewellery"],
    "C. Krishniah Chetty": ["c krishniah chetty", "ckc"],
    "Amrapali Jewels": ["amrapali jewels"],
    "Birdhichand Ghanshyamdas": ["birdhichand ghanshyamdas"],
    "Kantilal Chhotalal": ["kantilal chhotalal"],
    "CaratLane": ["caratlane"],
    "BlueStone": ["bluestone"],
    "Mia by Tanishq": ["mia by tanishq", "mia jewellery"],
    "Melorra": ["melorra"],
    "GIVA": ["giva jewellery"],
    "Palmonas": ["palmonas"],
    "Limelight Diamonds": ["limelight diamonds"],
    "Jewelbox": ["jewelbox jewellery"],
    "Fiona Diamonds": ["fiona diamonds"],
    "Avtaara": ["avtaara jewellery"],
    "Ivana": ["ivana jewellery"],
    "Kushal’s Fashion Jewellery": ["kushals jewellery", "kushal fashion jewellery"],
    "Rubans": ["rubans jewellery"],
    "Isharya": ["isharya jewellery"],
    "Outhouse": ["outhouse jewellery"],
    "Zaveri Pearls": ["zaveri pearls"],
    "Salty": ["salty jewellery"]
}


# =========================================================
# 3. HELPERS
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
    return (now - dt) <= timedelta(hours=24)


def fetch_news() -> List[Dict]:
    items = []
    seen = set()
    idx = 1

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get("title", feed_url)
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        recent = [e for e in entries if is_recent(e)]
        use_entries = recent if recent else entries

        for e in use_entries:
            if len(items) >= MAX_TOTAL_ITEMS:
                return items

            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            summary = (e.get("summary") or "").strip()

            if not title or not link:
                continue

            key = title.lower()
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "id": idx,
                "source": source,
                "title": title,
                "summary": summary,
                "link": link
            })
            idx += 1

    return items


def detect_brand_news(items: List[Dict]) -> Dict[str, List[Dict]]:
    brand_hits = {}

    for item in items:
        text = f"{item['title']} {item['summary']}".lower()

        for brand, keywords in TARGET_BRANDS.items():
            for kw in keywords:
                if kw in text:
                    brand_hits.setdefault(brand, [])
                    brand_hits[brand].append({
                        "title": item["title"],
                        "link": item["link"]
                    })
                    break

    return brand_hits



def build_headlines_text(items: List[Dict]) -> str:
    return "\n".join(
        f"{i['id']}) [{i['source']}] {i['title']}"
        for i in items
    )


def pick_editorial(items: List[Dict]) -> Dict:
    return items[0]

# =========================================================
# 4. OPENAI – CEO INTELLIGENCE + DAILY CRAFT LEARNING
# =========================================================

def ask_ai_for_digest(headlines_text: str, editorial: Dict, brand_news: Dict) -> str:
    client = OpenAI()
    today = datetime.now(IST).strftime("%Y-%m-%d")

    brand_context = ""
    for brand, articles in brand_news.items():
        brand_context += f"\n{brand}:\n"
        for a in articles:
            brand_context += f"- {a['title']} ({a['link']})\n"

    prompt = f"""
You are mentoring a senior jewellery procurement & merchandising leader
being trained for CEO responsibility.

Date: {today}
India is the core market.

HEADLINES:
{headlines_text}

EDITORIAL MUST-READ ARTICLE:
Title: {editorial['title']}
Link: {editorial['link']}

BRAND-SPECIFIC MARKET NEWS (FACTUAL ONLY):
{brand_context if brand_context else "No brand-specific corporate news detected today."}

OUTPUT RULES:
- HTML only
- Blunt, practical, decision-oriented
- SIGNAL → IMPACT → COMMAND
- Long-form intelligence is encouraged
- Mention brands ONLY if listed above
- Cite article links when referencing brands

MANDATORY SECTIONS:

<h2>🔎 Executive Snapshot</h2>

<h2>🌍 Macro & Policy Drivers</h2>

<h2>🪙 Gold & Silver Reality</h2>

<h2>💎 Diamonds & Polki Pipeline</h2>

<h2>🇮🇳 India Demand Reality</h2>

<h2>📦 What Is Selling vs What Is Stuck</h2>

<h2>🧵 Product & Craft Intelligence (Daily Craft Learning)</h2>

Each day, pick 1–2 jewellery product styles or crafts
(even if not in today’s news) and TEACH them deeply.

For EACH product, cover EXACTLY in this order:

<b>1. What It Is (Visual & Emotional Description)</b><br>
Describe how it looks, feels, and why customers find it beautiful.
Explain how a salesperson should describe it.

<b>2. How It Is Made (Step-by-Step)</b><br>
Explain the manufacturing process from raw metal to finished piece.

<b>3. Type of Workmanship</b><br>
Handmade / die-stamp / casting / mixed.

<b>4. Making Charges (Reality)</b><br>
Approximate making charge range.
Differentiate karigar cost vs retail billing logic.

<b>5. Margin Logic</b><br>
Where margin really comes from.

<b>6. Risk & Sourcing Complexity</b><br>
Skill dependency, repair risk, scalability.

<b>7. Who Buys This & When</b><br>
Region, occasion, buyer mindset.

<b>8. One Line of Craft Wisdom</b><br>
A sentence that proves mastery.

<h2>📰 Editorial Must-Read</h2>

<h2>🎯 Strategic Question of the Day</h2>

<h2>🧠 Procurement → CEO Lens</h2>
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        temperature=0.35,
        max_output_tokens=1900
    )

    return response.output_text.strip()

# =========================================================
# 5. EMAIL
# =========================================================

def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject

    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls(context=context)
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)

# =========================================================
# 6. MAIN
# =========================================================

def main():
    news = fetch_news()
    if not news:
        send_email("Jewellery Digest", "<p>No material news today.</p>")
        return

    brand_news = detect_brand_news(news)
    editorial = pick_editorial(news)
    headlines_text = build_headlines_text(news)

    digest = ask_ai_for_digest(
        headlines_text=headlines_text,
        editorial=editorial,
        brand_news=brand_news
    )

    subject = f"Jewellery Procurement → CEO Intelligence | {datetime.now(IST).strftime('%d %b %Y')}"
    send_email(subject, digest)


if __name__ == "__main__":
    main()
