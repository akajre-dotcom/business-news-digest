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
]

MAX_ITEMS_PER_FEED = 8
MAX_TOTAL_ITEMS = 30
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

HIGH_VALUE_TERMS = [
    "gold", "import duty", "policy", "export",
    "earnings", "margin", "diamond",
    "lab grown", "retail expansion",
    "gst", "manufacturing", "karigar"
]

def score_item(item: Dict) -> int:
    text = (item["title"] + " " + item["summary"]).lower()
    score = 0

    for term in HIGH_VALUE_TERMS:
        if term in text:
            score += 2

    return score


# =========================================================
# FETCH NEWS
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

    items = sorted(items, key=lambda x: x["score"], reverse=True)

    logging.info(f"Fetched {len(items)} high-signal recent articles.")
    return items[:MAX_TOTAL_ITEMS]


# =========================================================
# CLUSTERING
# =========================================================

def cluster_news(items: List[Dict]) -> Dict[str, List[Dict]]:
    clusters = {
        "macro": [],
        "commodities": [],
        "diamonds": [],
        "retail": [],
        "craft": []
    }

    for item in items:
        text = (item["title"] + item["summary"]).lower()

        if any(k in text for k in ["policy", "gst", "duty", "trade", "export"]):
            clusters["macro"].append(item)

        if "gold" in text or "silver" in text:
            clusters["commodities"].append(item)

        if any(k in text for k in ["diamond", "polki", "lab grown"]):
            clusters["diamonds"].append(item)

        if any(k in text for k in ["retail", "store", "expansion", "earnings"]):
            clusters["retail"].append(item)

        if any(k in text for k in ["manufacturing", "karigar", "design"]):
            clusters["craft"].append(item)

    return clusters


def format_cluster(cluster_items):
    return "\n".join(
        f"- TITLE: {i['title']}\n"
        f"  SOURCE: {i['source']}\n"
        f"  SUMMARY: {i['summary']}\n"
        for i in cluster_items[:5]
    )


# =========================================================
# STRUCTURE VALIDATION
# =========================================================

REQUIRED_SECTIONS = [
    "Executive Signal (3 Minutes)",
    "Commodity & Capital Impact",
    "Supplier Power & Risk Map",
    "Retail & Consumer Shift",
    "Product Intelligence Deep Dive",
    "Margin & Working Capital Lens",
    "CEO Capital Allocation View",
    "Strategic Question for You",
    "Action for Today (Sourcing Head Mode)"
]

def validate_sections(html: str) -> bool:
    return all(f"<h2>{s}</h2>" in html for s in REQUIRED_SECTIONS)


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return str(soup)


# =========================================================
# AI GENERATION (MECHANISTIC MODE)
# =========================================================

def generate_digest(news: List[Dict]) -> str:

    clusters = cluster_news(news)

    structured_context = f"""
MACRO NEWS:
{format_cluster(clusters["macro"])}

COMMODITY NEWS:
{format_cluster(clusters["commodities"])}

DIAMOND NEWS:
{format_cluster(clusters["diamonds"])}

RETAIL NEWS:
{format_cluster(clusters["retail"])}

CRAFT NEWS:
{format_cluster(clusters["craft"])}
"""

    prompt = f"""
You are training a sourcing head to become a CEO in the jewellery industry.

You are NOT allowed to use generic corporate language such as:
innovation, strategic expansion, volatility management, strong growth, confidence.

Every statement must tie directly to a specific news item provided.

For each development:
- State what happened (specific)
- State operational consequence
- State sourcing impact
- State margin impact (estimate % where possible)
- State CEO implication

If detail is missing, explicitly say so.

Quantify wherever possible:
- Making charge ranges
- Gross margin bands
- Inventory days effect
- Supplier credit impact

HTML ONLY.
Every paragraph inside <p>.
Every section title inside <h2>.
No markdown.
No emojis.

MANDATORY SECTIONS:

<h2>Executive Signal (3 Minutes)</h2>
<h2>Commodity & Capital Impact</h2>
<h2>Supplier Power & Risk Map</h2>
<h2>Retail & Consumer Shift</h2>
<h2>Product Intelligence Deep Dive</h2>
<h2>Margin & Working Capital Lens</h2>
<h2>CEO Capital Allocation View</h2>
<h2>Strategic Question for You</h2>
<h2>Action for Today (Sourcing Head Mode)</h2>

NEWS INPUT:
{structured_context}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.2,
        max_output_tokens=3000
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
        send_email("Jewellery CEO Intelligence", "<p>No high-signal jewellery news today.</p>")
        return

    try:
        digest = generate_digest(news)
    except Exception as e:
        logging.error(str(e))
        send_email("Jewellery Intelligence ERROR", f"<p>{str(e)}</p>")
        return

    subject = f"Jewellery CEO Intelligence | {datetime.now(IST).strftime('%d %b %Y')}"
    send_email(subject, digest)


if __name__ == "__main__":
    main()
