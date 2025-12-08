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


def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Calls OpenAI to:
    - Apply editorial filtering
    - Create precise story groups (no over-grouping)
    - Categorise into sections
    - Output clean, newspaper-quality HTML
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()  # reads OPENAI_API_KEY from environment

    prompt = f"""
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

EDITORIAL GROUPING PRINCIPLES:

1. Group items ONLY when they clearly refer to the SAME SPECIFIC EVENT.
   Examples:
   - Same airline disruption reported by multiple media outlets.
   - Same RBI decision mentioned in multiple headlines.
   - Same earnings report, funding round, merger announcement, regulation, or macro data release.

2. Keep stories SEPARATE when:
   - They are different events in the same sector.
   - They involve the same company but different issues or announcements.
   - They concern different market movements or economic opinions.

3. When uncertain → KEEP AS SEPARATE GROUPS.

4. HARD RULES:
   - EVERY remaining item must appear in EXACTLY ONE story group.
   - NO item may appear in more than one group.
   - NO item may be omitted (except items excluded by newsroom filtering).

5. BALANCE RULE – AVOID DIGEST DOMINATION:
   - If a story cluster has more than 15 items, split into:
       (a) a main story group  
       (b) one overflow group  
   - Never create more than TWO groups for the same underlying event.
   - Keep the digest diverse and readable.

6. Aim for professional editorial judgment:
   - Groups should resemble how stories appear on a real business news homepage.


==============================================================
TASK 2 – ASSIGN EACH GROUP TO ONE SECTION
==============================================================

Each story group must belong to EXACTLY ONE of:

A. 🇮🇳 India – Economy, Markets, Corporate, Sectors, Startups & Deal
B. Global – Economy, Markets, Corporate, Sectors, Startups & Deal
C. Jewellery, Gold, Gems & Retail  
D. Other Business related & Consumer Trends 
E. Stock Market - Share, Price etc

Choose the section best matching the *main focus* of the group.


==============================================================
TASK 3 – OUTPUT FORMAT (STRICT HTML ONLY)
==============================================================

For each section you use, output:

<h2>SECTION TITLE</h2>
<div class="section">

  <div class="story">
    <h3>
      <a href="MAIN_LINK" target="_blank">MAIN HEADLINE (Source)</a>
    </h3>

    <p><b>Summary:</b>
       1–3 sentences in clean, neutral English. Summarise ONLY what can be inferred
       from the grouped titles. Do NOT invent details or dates.
    </p>

    <!-- Include this ONLY if group has multiple items -->
    <ul>
      <li><b>Also covered by:</b></li>
      <ul>
        <li>Source – <a href="LINK_2" target="_blank">LINK_2</a></li>
        <li>Source – <a href="LINK_3" target="_blank">LINK_3</a></li>
      </ul>
    </ul>
  </div>

</div>

RULES FOR MAIN HEADLINE:
- Choose the clearest headline that represents the event.
- Use its link as the MAIN_LINK.
- All others go under “Also covered by”.

==============================================================
NON-NEGOTIABLE OUTPUT RULES
==============================================================

- Use ONLY information from input titles.
- NO numeric IDs in final HTML.
- NO invented URLs or facts.
- NO text outside HTML.
- NO <html>, <head> or <body> tags.
- Output must be pure HTML.

End of instructions.
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        max_output_tokens=6500,
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
