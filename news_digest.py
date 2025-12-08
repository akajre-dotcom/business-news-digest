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

MAX_ITEMS_PER_FEED = 20   # ⬅️ smaller, balanced per feed
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

You are an expert business journalist and senior newsroom editor.

You receive a flat list of news items from multiple business, finance, markets, industry, and jewellery RSS feeds.
Each item has: numeric ID, [Source], Title, Link.

INPUT ITEMS:
{headlines_text}


==============================================================
BEFORE GROUPING – APPLY PROFESSIONAL NEWSROOM FILTER
==============================================================

Filter the headlines STRICTLY, as a real business editor would.

KEEP ONLY stories with *clear* business, economic, financial, corporate,
industry, markets, regulatory, commodities, or macro relevance.

Exclude completely (do NOT summarise, do NOT group, do NOT output):
- Celebrity / influencer / entertainment / OTT / gossip items.
- Crime, FIRs, court cases unless they directly affect a business, market, or company.
- Viral videos, social-media drama, human-interest stories.
- Politics with no measurable economic or regulatory consequence.
- Local accidents, weather, disasters, lifestyle stories, travel guides.
- Irrelevant consumer content without business impact.

KEEP headlines ONLY IF they directly affect:
- Companies, sectors, competition, corporate governance.
- Stock markets, bonds, commodities, currencies, crypto.
- RBI/central bank actions, regulation, taxation, policy changes.
- Trade, macro data, inflation, GDP, exports/imports.
- Startups, funding rounds, M&A, IPOs, PE/VC deals.
- Jewellery/gold/gems/diamond retail trends with commercial impact.

If relevance is not obvious → EXCLUDE.


==============================================================
TASK 1 – CREATE PRECISE STORY GROUPS (STRICT)
==============================================================

Your goal is to identify news items that describe the *same underlying event*.

EDITORIAL GROUPING PRINCIPLES (universal, not tied to any company):

1. Group items ONLY when they clearly refer to the SAME SPECIFIC EVENT.

2. Treat headlines as SEPARATE when:
   - They relate to different events even within the same sector.
   - They mention the same company but deal with different announcements.
   - They cover different market movements, economic opinions, forecasts, etc.

3. When uncertain → KEEP THEM IN SEPARATE GROUPS.
   Over-merging is worse than under-merging.

4. HARD RULES:
   - EVERY input item (every ID) MUST appear in exactly ONE story group.
   - NO item may appear in more than one group.
   - NO item may be silently dropped (except those removed in the newsroom filter).

5. BALANCE RULE – AVOID DOMINATION:
   To maintain a readable, newspaper-quality digest:
   - Do NOT allow any single event to dominate the briefing.
   - If a story has more than 6 related items, create:
       (a) one main story group, and  
       (b) one overflow group for the remaining related headlines.
   - Never produce more than TWO groups about the same event.
   - This rule applies to ALL events, generically.

6. Maintain overall diversity:
   Your grouping must ensure the digest covers a range of sectors, markets,
   corporate activity, policy developments, and global macro themes.


==============================================================
TASK 2 – ASSIGN STORY GROUPS TO SECTIONS
==============================================================

Each story group must be placed in EXACTLY ONE of these sections:

A. 🇮🇳 India – Economy & Markets
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
C. 🌏 Global – Markets & Macro
D. 💍 Jewellery, Gold, Gems & Retail
E. 🧩 Other Business & Consumer Trends

Choose the section that best represents the *main focus* of the group.


==============================================================
TASK 3 – OUTPUT FORMAT (STRICT HTML-ONLY)
==============================================================

For each section you use, output:

<h2>SECTION TITLE</h2>
<div class="section">

  <div class="story">
    <h3>
      <a href="MAIN_LINK" target="_blank">MAIN HEADLINE (Source)</a>
    </h3>

    <p><b>Summary:</b>
       1–3 crisp sentences in clean, neutral English, combining ONLY the facts
       implied by the grouped titles. Do NOT invent details not present in the input.
    </p>

    <!-- Include this ONLY if the group has multiple items -->
    <ul>
      <li><b>Also covered by:</b></li>
      <ul>
        <li>Source – <a href="LINK_2" target="_blank">LINK_2</a></li>
        <li>Source – <a href="LINK_3" target="_blank">LINK_3</a></li>
      </ul>
    </ul>
  </div>

  <!-- More <div class="story"> blocks, one per story group -->

</div>

RULES FOR MAIN HEADLINE SELECTION:
- Pick the clearest headline that best describes the event.
- Use its link as MAIN_LINK.
- All other group items go under “Also covered by”.

==============================================================
ADDITIONAL HARD CONSTRAINTS
==============================================================

- Do NOT use numeric IDs in the final output.
- Do NOT invent URLs, facts, or details.
- Do NOT output anything outside the required HTML.
- Do NOT include <html>, <head>, or <body>.
- The output must be valid HTML only.
- Use ONLY the text provided. No external knowledge.

End of instructions.


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
