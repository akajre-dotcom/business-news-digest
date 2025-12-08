import os
import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import List, Dict
import time

import feedparser
import pytz


# =======================
# 1. CONFIG
# =======================

RSS_FEEDS = [
    "https://www.livemint.com/rss/news",
    "https://www.livemint.com/rss/companies",
    "https://www.livemint.com/rss/markets",
    "https://www.livemint.com/rss/industry",
    "https://www.livemint.com/rss/money",
    "https://www.business-standard.com/rss/latest.rss",
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    "http://feeds.hindustantimes.com/HT-Business?format=xml",
    "https://indianexpress.com/section/business/feed/",
    "https://news.google.com/rss/search?q=jewellery+OR+gold+OR+gems+OR+diamond+retail&hl=en-IN&gl=IN&ceid=IN:en",
    "https://indianexpress.com/section/business/market/feed/",
    "https://economictimes.indiatimes.com/rssfeeds/1373380680.cms",
    "https://news.google.com/rss/search?q=site:moneycontrol.com+markets&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 20
IST = pytz.timezone("Asia/Kolkata")


# =======================
# 2. HELPER — CHECK IF ARTICLE IS WITHIN 24 HOURS
# =======================

def is_recent(entry):
    """Return True only if article is published in the last 24 hours."""
    now = datetime.now(IST)

    dt = None

    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)

    if dt is None:
        return False  # Cannot confirm date → skip

    return (now - dt) <= timedelta(hours=24)


# =======================
# 3. FETCH HEADLINES
# =======================

def fetch_news() -> List[Dict]:
    all_feeds = []

    for feed_url in RSS_FEEDS:
        print(f"[INFO] Reading RSS: {feed_url}")

        feed = feedparser.parse(feed_url)
        feed_title = feed.feed.get("title", feed_url)

        items = []

        for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
            # Filter last 24 hours
            if not is_recent(entry):
                continue

            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            items.append({"title": title, "link": link})

        print(f"[INFO] {len(items)} recent headlines from: {feed_title}")

        if items:
            all_feeds.append({"feed_title": feed_title, "items": items})

    return all_feeds


# =======================
# 4. BUILD HTML DIGEST
# =======================

def build_digest_html(news_by_feed: List[Dict]) -> str:
    parts = []

    for feed in news_by_feed:
        feed_title = feed["feed_title"]
        items = feed["items"]

        parts.append(f'<h2 style="margin-top:20px; font-size:18px; color:#222;">{feed_title}</h2>')
        parts.append('<ul style="padding-left:18px; margin-top:8px; margin-bottom:8px;">')

        for item in items:
            parts.append(
                f'<li style="margin-bottom:6px;">'
                f'<a href="{item["link"]}" target="_blank" style="text-decoration:none; color:#0066cc;">'
                f'{item["title"]}</a></li>'
            )

        parts.append('</ul>')

    if not parts:
        return "<p>No headlines found from last 24 hours.</p>"

    return "\n".join(parts)


# =======================
# 5. SEND EMAIL
# =======================

def send_email(subject: str, digest_html: str):
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")

    html = f"""
    <html><body style="margin:0; padding:0; background-color:#f5f5f5;">
      <div style="max-width:800px; margin:20px auto; font-family:Arial, sans-serif;">
        <div style="background:#ffffff; border-radius:12px; padding:20px 26px;">
          
          <h1 style="margin:0 0 4px 0; font-size:22px; color:#111;">
            📊 Business Headlines – Last 24 Hours
          </h1>
          <p style="margin:0; color:#777; font-size:12px;">
            Generated on <b>{now_ist}</b>
          </p>

          <hr style="margin:16px 0; border:none; border-top:1px solid #eee;">
          <div style="font-size:14px; color:#222; line-height:1.6;">
            {digest_html}
          </div>

        </div>
      </div>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls(context=context)
        server.login(smtp_username, smtp_password)
        server.send_message(msg)


# =======================
# 6. MAIN
# =======================

def main():
    news_by_feed = fetch_news()
    digest_html = build_digest_html(news_by_feed)

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Business Headlines – Last 24 Hours – {now_ist}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
