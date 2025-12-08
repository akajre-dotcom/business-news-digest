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

MAX_ITEMS_PER_FEED = 8   # ⬅️ smaller, balanced per feed
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
        # No reliable date → treat as not-recent for the first pass
        return False

    return (now - dt) <= timedelta(hours=24)


# =======================
# 3. FETCH HEADLINES (LAST 24H + FALLBACK, UNIQUE BY LINK)
# =======================

def fetch_news() -> List[Dict]:
    """
    Returns flat list of items:
      {id, source, title, link}

    Logic:
      - For each feed:
        - Try to pick only items from last 24 hours.
        - If none found, fallback to latest items (no time filter).
      - Deduplicate by link across all feeds.
    """
    items: List[Dict] = []
    seen_links = set()
    idx = 1

    for feed_url in RSS_FEEDS:
        print(f"[INFO] Reading RSS: {feed_url}")
        feed = feedparser.parse(feed_url)

        feed_title = feed.feed.get("title", feed_url)
        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        # First pass: only recent items
        recent_entries = [e for e in entries if is_recent(e)]

        # If no recent items, fallback to latest entries regardless of time
        if recent_entries:
            used_entries = recent_entries
            print(f"[INFO] Using {len(recent_entries)} recent items from: {feed_title}")
        else:
            used_entries = entries
            print(f"[INFO] No recent items (24h) from {feed_title}, using latest {len(entries)} instead.")

        count_added_from_feed = 0
        for entry in used_entries:
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
            count_added_from_feed += 1

        print(f"[INFO] Added {count_added_from_feed} unique items from: {feed_title}")

    print(f"[INFO] Total unique headlines collected (recent + fallback): {len(items)}")
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

    # ❌ REMOVE this truncation – it was cutting off later feeds
    # if len(text) > 15000:
    #     text = text[:15000]

    return text


# =======================
# 4. CALL OPENAI – CLUSTER + CATEGORIZE
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - Read all headlines (titles + sources + links)
    - Group items about the same event into story groups
    - Ensure EVERY item is used exactly once
    - Output grouped HTML with main + also-covered-by links
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

---------------- TASK 1 – CREATE STORY GROUPS ----------------
Your job is to:
- Create "story groups", where each group contains one or more items.
- Items belong to the same group if they clearly refer to the same underlying event
  (same company and same main action; or same policy decision; or same macro data print).

VERY IMPORTANT:
- You MUST assign EVERY input item (each ID) to EXACTLY ONE story group.
- Do NOT ignore, drop or merge away any item.
- Some groups will have only 1 item (that's fine).
- Some groups will have many items (same event covered by different sources).

---------------- TASK 2 – CATEGORISE EACH STORY GROUP ----------------
Assign each story group to exactly ONE of these sections:

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
For each section you actually use, output:

<h2>SECTION TITLE</h2>
<div class="section">
  <div class="story">
    <h3>MAIN HEADLINE (Main Source)</h3>
    <p><b>Summary:</b> 1–3 sentences in simple English, combining information from the grouped headlines.
       Only use what can be inferred from the titles and sources. Do NOT invent numbers or details.</p>
    <ul>
      <li><b>Main link:</b> <a href="MAIN_LINK" target="_blank">MAIN_LINK</a></li>
      <!-- If there are extra items in this group: -->
      <li><b>Also covered by:</b></li>
      <ul>
        <li>Source XYZ – <a href="LINK_2" target="_blank">LINK_2</a></li>
        <li>Source ABC – <a href="LINK_3" target="_blank">LINK_3</a></li>
      </ul>
      <!-- If the group has only one item, OMIT the "Also covered by" line and inner list entirely. -->
    </ul>
  </div>

  <!-- more <div class="story"> blocks, one per story group -->
</div>

Rules for choosing MAIN HEADLINE and MAIN LINK:
- Pick any one item in the group whose headline best describes the event.
- Its link becomes MAIN_LINK.
- All other items in the same group go under "Also covered by".

---------------- HARD CONSTRAINTS ----------------
- EVERY input item must appear in exactly ONE story group.
- NO item may be omitted.
- NO item may appear in more than one group.
- Do NOT output the numeric IDs in the final HTML (they are for your internal grouping only).
- Do NOT invent any story or URL; ONLY use the Titles, Sources, and Links provided.
- Do NOT output any text outside HTML tags.
- Do NOT output <html>, <head>, or <body> tags.

Use ONLY information from titles and sources. No external knowledge.
Output MUST be valid HTML only. No markdown, no explanations.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        max_output_tokens=6000,
        temperature=0.2,
    )

    return response.output_text.strip()




# =======================
# 5. SEND NICE HTML EMAIL
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
    <html>
      <body style="margin:0; padding:0; background-color:#f5f5f5;">
        <div style="max-width:800px; margin:20px auto; font-family:Arial, sans-serif;">
          <div style="background:#ffffff; border-radius:12px; padding:20px 26px; box-shadow:0 2px 10px rgba(0,0,0,0.08);">
            
            <h1 style="margin:0 0 4px 0; font-size:22px; color:#111;">
              📊 Business News Digest – Clustered Headlines
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
        digest_html = "<p>No headlines found from RSS feeds.</p>"
    else:
        headlines_text = build_headlines_text(news_items)
        digest_html = ask_ai_for_digest(headlines_text)

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Business News Digest – {now_ist}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
