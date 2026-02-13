import os
import ssl
import smtplib
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict

import feedparser
import pytz
from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

RSS_FEEDS = [
    "https://www.gold.org/rss/news",
    "https://rapaport.com/feed/",
    "https://www.solitaireinternational.com/feed/",
    "https://news.google.com/rss/search?q=India+jewellery+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=diamond+industry+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=gold+import+duty+India&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 12
MAX_TOTAL_ITEMS = 60
IST = pytz.timezone("Asia/Kolkata")

logging.basicConfig(level=logging.INFO)
client = OpenAI()


# =========================================================
# RECENCY FILTER
# =========================================================

def is_recent(entry) -> bool:
    now = datetime.now(IST)
    dt = None

    if entry.get("published_parsed"):
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif entry.get("updated_parsed"):
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)

    return dt and (now - dt) <= timedelta(hours=24)


# =========================================================
# SIGNAL SCORING
# =========================================================

KEY_TERMS = [
    "gold", "silver", "diamond", "polki", "lab grown",
    "export", "import", "duty", "policy", "gst",
    "earnings", "margin", "retail", "expansion",
    "manufacturing", "karigar", "wastage"
]

def score_item(item: Dict) -> int:
    text = (item["title"] + " " + item["summary"]).lower()
    return sum(1 for term in KEY_TERMS if term in text)


# =========================================================
# FETCH & FILTER
# =========================================================

def fetch_news() -> List[Dict]:
    items, seen = [], set()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for e in feed.entries[:MAX_ITEMS_PER_FEED]:

            if not is_recent(e):
                continue

            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            summary = (e.get("summary") or "").strip()

            if not title or not link:
                continue

            if title.lower() in seen:
                continue

            seen.add(title.lower())

            item = {
                "source": feed.feed.get("title", "Unknown"),
                "title": title,
                "summary": summary,
                "link": link,
            }

            item["score"] = score_item(item)
            items.append(item)

    # Sort by relevance score
    items = sorted(items, key=lambda x: x["score"], reverse=True)

    # Keep top 50% most relevant
    cutoff = max(10, len(items) // 2)
    filtered = items[:cutoff]

    logging.info(f"Selected {len(filtered)} high-relevance articles.")
    return filtered


# =========================================================
# VALIDATION
# =========================================================

REQUIRED_SECTIONS = [
    "Executive Snapshot",
    "Macro & Policy Drivers",
    "Gold & Silver Reality",
    "Diamonds & Polki Pipeline",
    "India Demand Reality",
    "What Is Selling vs What Is Stuck",
    "Product & Craft Intelligence",
    "Editorial Must-Read",
    "Strategic Question of the Day",
    "Procurement → CEO Lens"
]

def validate_sections(html: str) -> bool:
    return all(f"<h2>{s}</h2>" in html for s in REQUIRED_SECTIONS)


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return str(soup)


# =========================================================
# AI GENERATION
# =========================================================

def generate_digest(news: List[Dict]) -> str:

    context = "\n".join(
        f"- TITLE: {i['title']}\n  SOURCE: {i['source']}\n  SUMMARY: {i['summary']}\n"
        for i in news[:30]
    )

    prompt = f"""
You are a master of the global jewellery industry.

Use only the relevant developments below.
Ignore weak or trivial news.

No repetition of the same company across more than two sections.

No corporate filler language.
Every claim must connect to a real development from the input.

If signal concentration is narrow today, state that clearly.

HTML only.
Each paragraph wrapped in <p>.
Each section title wrapped in <h2>.

MANDATORY SECTIONS:

<h2>Executive Snapshot</h2>
<h2>Macro & Policy Drivers</h2>
<h2>Gold & Silver Reality</h2>
<h2>Diamonds & Polki Pipeline</h2>
<h2>India Demand Reality</h2>
<h2>What Is Selling vs What Is Stuck</h2>
<h2>Product & Craft Intelligence</h2>
<h2>Editorial Must-Read</h2>
<h2>Strategic Question of the Day</h2>
<h2>Procurement → CEO Lens</h2>

NEWS INPUT:
{context}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.25,
        max_output_tokens=3500
    )

    html = response.output_text.strip()

    if not validate_sections(html):
        raise ValueError("Digest failed structural validation.")

    return sanitize_html(html)


# =========================================================
# EMAIL
# =========================================================

def send_email(subject: str, html: str):

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            font-size: 15px;
        }}
        h2 {{
            margin-top: 28px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 4px;
        }}
        p {{
            margin: 10px 0;
        }}
        </style>
    </head>
    <body>
        {html}
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject

    msg.attach(MIMEText(full_html, "html"))

    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)

    logging.info("Email sent successfully.")


# =========================================================
# MAIN
# =========================================================

def main():

    news = fetch_news()

    if not news:
        send_email("Jewellery Intelligence", "<p>No high-relevance jewellery news today.</p>")
        return

    try:
        digest = generate_digest(news)
    except Exception as e:
        logging.error(str(e))
        send_email("Jewellery Intelligence ERROR", f"<p>{str(e)}</p>")
        return

    subject = f"Jewellery Intelligence | {datetime.now(IST).strftime('%d %b %Y')}"
    send_email(subject, digest)


if __name__ == "__main__":
    main()
