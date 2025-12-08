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
from openai import OpenAI


# =======================
# 1. CONFIG
# =======================

RSS_FEEDS = [
    # --- Livemint (updated official RSS, no 'RSS' suffix) ---
    "https://www.livemint.com/rss/news",
    "https://www.livemint.com/rss/companies",
    "https://www.livemint.com/rss/markets",
    "https://www.livemint.com/rss/industry",
    "https://www.livemint.com/rss/money",

    # --- Business Standard ---
    "https://www.business-standard.com/rss/latest.rss",

    # --- Economic Times (default) ---
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",

    # --- Hindustan Times (Business – alternative RSS) ---
    "http://feeds.hindustantimes.com/HT-Business?format=xml",

    # --- Indian Express (Business main) ---
    "https://indianexpress.com/section/business/feed/",

    # --- Jewellery / Gold / Gems / Diamond retail (Google News) ---
    "https://news.google.com/rss/search?q=jewellery+OR+gold+OR+gems+OR+diamond+retail&hl=en-IN&gl=IN&ceid=IN:en",

    # --- Indian Express (Business – Markets) ---
    "https://indianexpress.com/section/business/market/feed/",

    # --- Economic Times (Economy) ---
    "https://economictimes.indiatimes.com/rssfeeds/1373380680.cms",

    # --- Moneycontrol (Markets via Google News) ---
    "https://news.google.com/rss/search?q=site:moneycontrol.com+markets&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 30  # how many entries to look at per feed
IST = pytz.timezone("Asia/Kolkata")


# =======================
# 2. HELPER — CHECK IF ARTICLE IS WITHIN 24 HOURS
# =======================

def is_recent(entry) -> bool:
    """Return True only if article is published in the last 24 hours (IST)."""
    now = datetime.now(IST)

    dt = None

    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), IST)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed), IST)

    if dt is None:
        # No date info → skip, to keep "last 24h" strict
        return False

    return (now - dt) <= timedelta(hours=24)


# =======================
# 3. FETCH HEADLINES (LAST 24H, UNIQUE BY LINK)
# =======================

def fetch_news() -> List[Dict]:
    """
    Returns flat list of items:
      {id, source, title, link}
    Only includes:
      - last 24 hours (IST)
      - unique links across all feeds
    """
    items: List[Dict] = []
    seen_links = set()
    idx = 1

    for feed_url in RSS_FEEDS:
        print(f"[INFO] Reading RSS: {feed_url}")
        feed = feedparser.parse(feed_url)

        feed_title = feed.feed.get("title", feed_url)

        count_recent = 0
        for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
            if not is_recent(entry):
                continue

            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            # Deduplicate by link across all feeds
            if link in seen_links:
                continue
            seen_links.add(link)

            items.append(
                {
                    "id": idx,
                    "source": feed_title,
                    "title": title,
                    "link": link,
                }
            )
            idx += 1
            count_recent += 1

        print(f"[INFO] {count_recent} recent unique headlines from: {feed_title}")

    print(f"[INFO] Total unique recent headlines collected: {len(items)}")
    return items


def build_headlines_text(items: List[Dict]) -> str:
    """
    Turn news items into a text block for the AI.
    Format:
      N) [Source: ...]
         Title: ...
         Link: ...
    """
    lines = []
    for item in items:
        lines.append(f"{item['id']}) [Source: {item['source']}]")
        lines.append(f"   Title: {item['title']}")
        lines.append(f"   Link: {item['link']}")
        lines.append("")

    text = "\n".join(lines)

    # Safety cap on size (should rarely hit)
    if len(text) > 15000:
        text = text[:15000]
    return text


# =======================
# 4. CALL OPENAI – CLUSTER + CATEGORIZE
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - Read headlines only (no article body)
    - Club similar news into single story when same event
    - Group stories into broader categories
    - Output HTML only
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()  # reads OPENAI_API_KEY from env

    prompt = f"""
You are an expert financial and business journalist for an Indian audience.

You receive a flat list of news items from multiple business/markets/jewellery RSS feeds.
Each item has: numeric ID, [Source], Title, Link.

INPUT ITEMS:
{headlines_text}

---------------- TASK 1 – DEDUP / CLUB STORIES ----------------
Your job is to:
- Identify items that clearly refer to the same underlying event
  (same company and same main action; or same policy decision; or same macro data print).
- Club them into a single "story group".

Rules:
- If two headlines are obviously about the same event from different sources, treat them as ONE story.
- If similar theme but clearly different events (different companies, dates, numbers), keep them separate.
- Each story group must reference ALL included links (main + additional).

---------------- TASK 2 – CATEGORISE EACH STORY ----------------
Assign each story group to exactly ONE of these categories:

A. 🇮🇳 India – Economy & Markets
   (RBI, GDP, inflation, fiscal, trade, indices, yields, Nifty, Sensex, macro data)
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
   (company news, results, earnings, funding, IPOs, M&A, sector-specific developments)
C. 🌏 Global – Markets & Macro
   (US/Europe/Asia macro, global markets, Fed, ECB, BOJ, global commodities, FX)
D. 💍 Jewellery, Gold, Gems & Retail
   (gold prices, jewellery demand, hallmarking, diamond/gem trade, jewellery retailers)
E. 🧩 Other Business & Consumer Trends
   (business + tech + consumer trends that don't fit cleanly above)

Every story group MUST go into exactly ONE of the above sections.

---------------- TASK 3 – OUTPUT FORMAT (HTML ONLY) ----------------
Output ONLY HTML, structured as:

For each category section you actually use:

<h2>SECTION TITLE</h2>
<div class="section">
  <div class="story">
    <h3>MAIN HEADLINE (Main Source)</h3>
    <p><b>Summary:</b> 1–3 sentences in simple English, combining information from the grouped headlines.
       Only use what can be inferred from the titles and sources. Do NOT invent numbers or details.</p>
    <ul>
      <li><b>Main link:</b> <a href="MAIN_LINK" target="_blank">MAIN_LINK</a></li>
      <li><b>Also covered by:</b></li>
      <ul>
        <li>Source XYZ – <a href="LINK_2" target="_blank">LINK_2</a></li>
        <li>Source ABC – <a href="LINK_3" target="_blank">LINK_3</a></li>
        <!-- omit this inner list entirely if there are no extra links -->
      </ul>
    </ul>
  </div>

  <!-- more <div class="story"> blocks within this section -->
</div>

Requirements:
- Choose the clearest or most complete headline as MAIN HEADLINE.
- For each story, always show at least the MAIN_LINK (the link from one of the grouped items).
- If only one item is in a group, then omit the "Also covered by" inner list.
- Do NOT invent any story or URL; ONLY use the IDs/titles/links given.
- Do NOT reference the numeric IDs in the final output; they are only for your grouping logic.

---------------- VERY IMPORTANT ----------------
- Use ONLY information available from titles and sources.
- No external knowledge, no invented numbers or dates.
- Output MUST be valid HTML only. No markdown. No explanations.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",      # cheaper, good enough for clustering
        input=prompt,
        max_output_tokens=2500,
        temperature=0.2,
    )

    return response.output_text.strip()


# =======================
# 5. SEND NICE HTML EMAIL
# =======================

def send_email(subject: str, digest_html: str):
    """Send a nicely formatted HTML email with the digest."""

    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")

    html = f"""
    <html>
      <body style="margin:0; padding:0; background-color:#f5f5f5;">
        <div style="max-width:800px; margin:20px auto; font-family:Arial, sans-serif;">
          <div style="background:#ffffff; border-radius:12px; padding:20px 26px; box-shadow:0 2px 10px rgba(0,0,0,0.08);">
            
            <h1 style="margin:0 0 4px 0; font-size:22px; color:#111;">
              📊 Business News Digest – Clustered Headlines (Last 24 Hours)
            </h1>
            <p style="margin:0; color:#777; font-size:12px;">
              Generated automatically on <b>{now_ist}</b> · Similar stories clubbed · Categorised by theme
            </p>

            <hr style="margin:16px 0; border:none; border-top:1px solid #eee;">

            <div style="font-size:14px; color:#222; line-height:1.6;">
              {digest_html}
            </div>

            <hr style="margin:20px 0; border:none; border-top:1px solid #eee;">

            <p style="font-size:11px; color:#999; margin:0;">
              🤖 This digest is auto-generated from multiple business news RSS feeds using AI.
              Stories are grouped when multiple sources cover the same event.
            </p>
          </div>
        </div>
      </body>
    </html>
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
    news_items = fetch_news()

    if not news_items:
        digest_html = "<p>No recent headlines found in the last 24 hours.</p>"
    else:
        headlines_text = build_headlines_text(news_items)
        digest_html = ask_ai_for_digest(headlines_text)

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Business News Digest – Last 24 Hours – {now_ist}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
