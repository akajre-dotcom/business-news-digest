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
# 0. TOP-LEVEL MASTER INSTRUCTION (NON-NEGOTIABLE)
# =========================================================

TOP_LEVEL_INSTRUCTION = """
You are not a summarizer.

You are a master of the global jewellery industry with deep, lived understanding of:
– Gold, silver, diamonds (natural, polki, uncut, LGD)
– Indian and global manufacturing systems
– Karigar workflows, failure points, and skill economics
– Trade margins, making charges, wastage logic, and pricing psychology
– Retail behaviour across India, Middle East, US, and Europe
– Luxury, heritage, and high jewellery storytelling

Your task is to turn raw market news, trade data, and craft references into
elite-level jewellery intelligence that teaches mastery.

For every output:
– Assume the reader wants to become a lifelong expert
– Explain WHY things are made the way they are, not just WHAT happened
– Translate news into manufacturing, margin, and design consequences
– Reveal hidden mechanics only insiders know
– Never write generic content or textbook definitions
– Never praise brands or marketing language
– Be precise, factual, and experience-driven

Your output should make a serious reader capable of:
– Judging jewellery quality on sight
– Understanding pricing without being told
– Describing beauty, craft, and value with authority
– Thinking like a procurement head today and a CEO tomorrow

If a detail is uncertain, explain the uncertainty.
If a practice is inefficient, say why.
If a craft is dying, explain what replaces it.
If something makes money, explain EXACTLY how.

Write so that repeated daily reading compounds into true mastery of the jewellery industry.
"""

# =========================================================
# 1. CONFIG
# =========================================================

RSS_FEEDS = [
    "https://www.gold.org/rss/news",
    "https://rapaport.com/feed/",
    "https://www.solitaireinternational.com/feed/",
    "https://news.google.com/rss/search?q=India+jewellery+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=jewellery+company+India+policy&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=jewellery+retail+store+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=jewellery+manufacturing+India+craft&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=handmade+gold+jewellery+India+design&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=diamond+polki+lab+grown+jewellery+India&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 8
MAX_TOTAL_ITEMS = 30
IST = pytz.timezone("Asia/Kolkata")

# =========================================================
# 2. TARGET BRAND KEYWORDS (NORMALIZED)
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
    if entry.get("published_parsed"):
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif entry.get("updated_parsed"):
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)
    return dt and (now - dt) <= timedelta(hours=24)


def fetch_news() -> List[Dict]:
    items, seen, idx = [], set(), 1

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get("title", "Unknown Source")
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        for e in entries:
            if len(items) >= MAX_TOTAL_ITEMS:
                return items

            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            summary = (e.get("summary") or "").strip()

            if not title or not link:
                continue

            if title.lower() in seen:
                continue
            seen.add(title.lower())

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
    hits = {}

    for item in items:
        text = f"{item['title']} {item['summary']}".lower()
        for brand, keywords in TARGET_BRANDS.items():
            if any(k in text for k in keywords):
                hits.setdefault(brand, []).append(item)
    return hits


def build_headlines_text(items: List[Dict]) -> str:
    return "\n".join(
        f"{i['id']}) <a href='{i['link']}'>{i['title']}</a>"
        for i in items
    )


def pick_editorial(items: List[Dict]) -> Dict:
    return items[0]

# =========================================================
# 4. OPENAI – INLINE LINK ENFORCED
# =========================================================

def ask_ai_for_digest(headlines_text: str, editorial: Dict, brand_news: Dict) -> str:
    client = OpenAI()
    today = datetime.now(IST).strftime("%Y-%m-%d")

    brand_context = ""
    for brand, articles in brand_news.items():
        for a in articles:
            brand_context += (
                f"- {brand}: "
                f"<a href='{a['link']}'>{a['title']}</a>\n"
            )

    prompt = f"""
{TOP_LEVEL_INSTRUCTION}

Date: {today}
India is the core market.

HEADLINES (ALL CLICKABLE):
{headlines_text}

EDITORIAL MUST-READ:
<a href="{editorial['link']}">{editorial['title']}</a>

BRAND-SPECIFIC MARKET SIGNALS:
{brand_context if brand_context else "No brand-specific corporate developments today."}

STRICT OUTPUT RULES:
- HTML only
- NO separate link lines
- NO reference sections
- ALL sources must be embedded as clickable text or headings
- Every cited fact must be naturally clickable
- Write like a master jeweller teaching an apprentice

MANDATORY SECTIONS:

<h2>🔎 Executive Snapshot</h2>
<h2>🌍 Macro & Policy Drivers</h2>
<h2>🪙 Gold & Silver Reality</h2>
<h2>💎 Diamonds & Polki Pipeline</h2>
<h2>🇮🇳 India Demand Reality</h2>
<h2>📦 What Is Selling vs What Is Stuck</h2>

<h2>🧵 Product & Craft Intelligence (Daily Craft Learning)</h2>
Teach 1–2 products deeply using visual language, process, margin, risk, buyer, and craft wisdom.

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

    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)

# =========================================================
# 6. MAIN
# =========================================================

def main():
    news = fetch_news()
    if not news:
        send_email("Jewellery Intelligence", "<p>No material jewellery news today.</p>")
        return

    brand_news = detect_brand_news(news)
    editorial = pick_editorial(news)
    headlines_text = build_headlines_text(news)

    digest = ask_ai_for_digest(headlines_text, editorial, brand_news)

    subject = f"Jewellery Procurement → CEO Intelligence | {datetime.now(IST).strftime('%d %b %Y')}"
    send_email(subject, digest)


if __name__ == "__main__":
    main()
