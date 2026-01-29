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

RSS_FEEDS = [
    "https://www.gold.org/rss/news",
    "https://rapaport.com/feed/",
    "https://www.solitaireinternational.com/feed/",
    "https://news.google.com/rss/search?q=India+jewellery+gold+diamond&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=GJEPC+jewellery+export+India&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 8
MAX_TOTAL_ITEMS = 30   # TPM-safe
IST = pytz.timezone("Asia/Kolkata")

DEFAULT_DIGEST_ROLE = "investor"

# =========================================================
# 2. HELPERS
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
                "link": link
            })
            idx += 1

    return items


def build_headlines_text(items: List[Dict]) -> str:
    return "\n".join(
        f"{i['id']}) [{i['source']}] {i['title']}"
        for i in items
    )


def pick_editorial(items: List[Dict]) -> Dict:
    """
    Pick the most recent / strategic article for Editorial Must-Read
    """
    return items[0]  # most recent due to ordering

# =========================================================
# 3. OPENAI – PROCUREMENT → CEO DIGEST
# =========================================================

def ask_ai_for_digest(headlines_text: str, editorial: Dict) -> str:
    client = OpenAI()
    today = datetime.now(IST).strftime("%Y-%m-%d")

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

OUTPUT RULES:
- HTML only
- Blunt, practical, decision-oriented
- SIGNAL → IMPACT → COMMAND

MANDATORY SECTIONS:

<h2>🔎 Executive Snapshot</h2>

<h2>🌍 Macro & Policy Drivers</h2>

<h2>🪙 Gold & Silver Reality</h2>

<h2>💎 Diamonds & Polki Pipeline</h2>

<h2>🇮🇳 India Demand Reality</h2>

<h2>📦 What Is Selling vs What Is Stuck</h2>

<h2>🧵 Product & Craft Intelligence (Procurement Mastery)</h2>
Explain manufacturing logic, making charges (retail vs karigar),
risk, margin, and sourcing complexity for:
- Handmade die/stamp, chillai, regi, filigree
- Slab 1/2, PJWS, Enamel, Jaali
- Kundan, Antique, Nakashi (die / hand / full)
- Casting vs Handmade
- Bangles: hollow, filigree, sankha, pola
- Direct casting combinations
Focus on how a procurement head should think.

<h2>📰 Editorial Must-Read</h2>
Explain why this article matters.
Include clickable link.

<h2>🎯 Strategic Question of the Day</h2>
Ask the question AND answer it as a CEO would.

<h2>🧠 Procurement → CEO Lens</h2>
What decision today builds long-term enterprise advantage?
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        temperature=0.35,
        max_output_tokens=1900
    )

    return response.output_text.strip()

# =========================================================
# 4. EMAIL
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
# 5. MAIN
# =========================================================

def main():
    news = fetch_news()
    if not news:
        send_email("Jewellery Digest", "<p>No material news today.</p>")
        return

    editorial = pick_editorial(news)
    headlines_text = build_headlines_text(news)
    digest = ask_ai_for_digest(headlines_text, editorial)

    subject = f"Jewellery Procurement → CEO Intelligence | {datetime.now(IST).strftime('%d %b %Y')}"
    send_email(subject, digest)

if __name__ == "__main__":
    main()
