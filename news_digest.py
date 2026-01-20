import os
import ssl
import smtplib
import time
import random
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
    # Gold / Macro
    "https://news.google.com/rss/search?q=World+Gold+Council+gold+demand&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=LBMA+gold+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=central+bank+gold+buying&hl=en-IN&gl=IN&ceid=IN:en",

    # Diamonds
    "https://news.google.com/rss/search?q=De+Beers+diamond+sales&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=ALROSA+diamond+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Rapaport+diamond+market&hl=en-IN&gl=IN&ceid=IN:en",

    # India Jewellery
    "https://news.google.com/rss/search?q=GJEPC+jewellery+export+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Surat+diamond+industry&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Jaipur+gems+industry&hl=en-IN&gl=IN&ceid=IN:en",

    # Middle East
    "https://news.google.com/rss/search?q=Dubai+gold+market+jewellery&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=UAE+jewellery+retail&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Saudi+Arabia+jewellery+luxury&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 15
IST = pytz.timezone("Asia/Kolkata")

# Default role (CEO / Promoter view)
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
        feed_title = feed.feed.get("title", feed_url)
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        recent = [e for e in entries if is_recent(e)]
        use_entries = recent if recent else entries

        for e in use_entries:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link or link in seen:
                continue

            seen.add(link)
            items.append({
                "id": idx,
                "source": feed_title,
                "title": title,
                "link": link,
            })
            idx += 1

    return items


def build_headlines_text(items: List[Dict]) -> str:
    lines = []
    for i in items:
        lines.append(f"{i['id']}) [Source: {i['source']}]")
        lines.append(f"   Title: {i['title']}")
        lines.append(f"   Link: {i['link']}")
        lines.append("")
    return "\n".join(lines)


# =========================================================
# 3. OPENAI – CEO-GRADE DIGEST
# =========================================================

def ask_ai_for_digest(headlines_text: str, digest_type: str) -> str:
    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI()

    ROLE_CONTEXT = {
        "retailer": "store economics, sell-through, customer behaviour",
        "manufacturer": "capacity, costs, working capital",
        "exporter": "US/ME demand, margins, currency",
        "miner": "supply discipline, pricing power",
        "trader": "price direction, risk",
        "investor": "capital allocation, cycle timing, winners vs losers"
    }

    prompt = f"""
You are a senior jewellery-industry mentor training promoters and CEOs.

PRIMARY ROLE: {digest_type.upper()}
Perspective: {ROLE_CONTEXT.get(digest_type, "")}

India is the core market.
Other regions matter only if they impact India.

INPUT HEADLINES:
{headlines_text}

OUTPUT:
Pure HTML only. Simple language. CEO mindset.

STRUCTURE:

<h2>🔎 Executive Snapshot</h2>
<ul>
<li>What changed.</li>
<li>Why it matters.</li>
<li>Who is winning and who is under pressure.</li>
</ul>

<h2>🌍 Macro & Policy Drivers</h2>
<ul>
<li>Rates, currency, regulation.</li>
</ul>

<h2>🪙 Gold & Silver Reality</h2>
<ul>
<li>Price vs demand.</li>
<li>Physical buying behaviour.</li>
</ul>

<h2>💎 Diamonds & Polki Pipeline</h2>
<ul>
<li>Supply vs inventory.</li>
<li>Natural vs lab-grown.</li>
</ul>

<h2>🇮🇳 India Demand Reality</h2>
<ul>
<li>Wedding and retail mood.</li>
<li>Urban vs rural signals.</li>
</ul>

<h2>🏢 Major Players – What They Are Really Doing</h2>
<ul>
<li>Tanishq, Kalyan, Malabar, PC Jeweller, Kisna, Indriya.</li>
</ul>

<h2>📦 What Is Selling vs What Is Stuck</h2>
<ul>
<li>Fast categories.</li>
<li>Slow inventory.</li>
</ul>

<h2>🧠 CEO Lens</h2>
<ul>
<li>Capital allocation insight.</li>
<li>Risk others ignore.</li>
<li>One long-term advantage to build.</li>
</ul>

<h2>📰 Editorial Must-Read</h2>
<ul>
<li>One article worth deep attention.</li>
</ul>

<h2>📐 Trend Check</h2>
<ul>
<li>Trend.</li>
<li>Fad, cycle, or structural.</li>
</ul>

<h2>🎯 Strategic Question of the Day</h2>
<p>
If you were the promoter, what decision deserves serious thought today?
</p>

RULES:
- Use only headline information
- No numbers if not stated
- Prefer uncomfortable truths
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        temperature=0.35,
        max_output_tokens=3000,
    )

    return response.output_text.strip()


# =========================================================
# 4. EMAIL SENDER
# =========================================================

def send_email(subject: str, html_content: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", "587"))) as server:
        server.starttls(context=context)
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)


# =========================================================
# 5. MAIN
# =========================================================

def main():
    news = fetch_news()

    if not news:
        send_email("Jewellery Digest", "<p>No news found.</p>")
        return

    headlines_text = build_headlines_text(news)
    digest_html = ask_ai_for_digest(headlines_text, DEFAULT_DIGEST_ROLE)

    now = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Jewellery CEO Intelligence Digest – {now}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
