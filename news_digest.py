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

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - Group only truly similar items (same event)
    - Use ALL items exactly once
    - Make headline clickable
    - Output clean grouped HTML
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()  # reads OPENAI_API_KEY from env

    prompt = f"""
You are an expert financial and business journalist for an audience.

You receive a flat list of news items from multiple business/markets/jewellery RSS feeds.
Each item has: numeric ID, [Source], Title, Link.

INPUT ITEMS:
{headlines_text}

---------------- BEFORE GROUPING – APPLY NEWSROOM FILTER ----------------
As a senior business editor, filter the input headlines STRICTLY.

You must EXCLUDE ALL ITEMS that do NOT have clear and direct business,
economic, financial, corporate, policy, markets, trade, commodities,
startup, taxation, banking, investing or industry relevance.

EXCLUDE completely (do not summarise, do not group, do not output):
- Celebrity news, influencers, actors, entertainment, movies, OTT, gossip.
- Crime reports, FIRs, court cases unrelated to business impact.
- Viral videos, memes, social media trends, public outbursts, human-interest stories.
- Pure politics without measurable economic or business consequence.
- General news: weather, accidents, natural disasters, protests, cultural events.
- Local incidents with zero corporate, regulatory, macroeconomic, retail, or investor impact.
- General lifestyle advice, travel stories, festival stories, personal anecdotes.

KEEP ONLY IF the item CLEARLY affects:
- Companies, sectors, earnings, growth, competitive dynamics.
- Markets: equities, debt, commodities, currencies, crypto, derivatives.
- Policy/regulation with business or economic impact.
- Banking, NBFCs, mutual funds, insurance, pensions, taxation.
- Macro indicators: GDP, inflation, RBI decisions, fiscal issues, trade data.
- Startups, funding, VC/PE, IPOs, acquisitions, mergers.
- Consumer behaviour-shifting trends WITH economic relevance.
- Jewellery, gold, gems, diamonds, bullion, hallmarking, retail trends.

If a headline’s economic/business impact is NOT obvious → **EXCLUDE IT**.
If the impact is indirect BUT real → **KEEP IT**.

After filtering, only use the remaining items for grouping and summary.


---------------- TASK 1 – CREATE STORY GROUPS (STRICTLY) ----------------
You are acting as a senior news editor responsible for organising headlines into
clean, publication-ready story groups.

Your goal is to identify which headlines refer to the **same underlying news event**.

EDITORIAL GROUPING RULES (STRICT):

1. Group items ONLY when they clearly describe the *exact same event*.
   Examples of valid grouping:
   - Multiple outlets reporting on the same IndiGo operational disruption.
   - Multiple headlines about the SAME RBI decision or liquidity action.
   - Different sources covering the SAME corporate announcement, earnings release,
     funding round, merger, regulation, or geopolitical incident.

2. Treat stories as SEPARATE when they are:
   - About different events within the same broad theme (e.g., general market moves,
     different RBI viewpoints, unrelated gold price changes).
   - About the same company but referring to different actions, dates, or issues.
   - About similar macro/economic topics but not about the same specific event.

3. When in doubt, DO NOT merge.
   It is always safer to keep two items in different groups than to incorrectly
   combine unrelated events.

4. Precision matters:
   - Two headlines are “related” only if a reader would reasonably expect them to
     appear under the same story on a news homepage.
   - Do not group items merely because they mention similar sectors, topics, or actors.

HARD NON-NEGOTIABLE RULES:

- EVERY input item (every ID) must appear in EXACTLY ONE story group.
- Do NOT omit, discard, or merge away any item.
- An item may NEVER appear in more than one group.
- Groups may contain:
  - 1 item (unique story)
  - Many items (same event covered by multiple sources)

Think like a professional editor producing a clean, organised briefing.
Your groupings must remain fact-based, conservative, and highly precise.


---------------- TASK 2 – CATEGORISE EACH GROUP ----------------
Assign each story group to exactly ONE of these sections:

A. 🇮🇳 India – Economy & Markets  
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals  
C. 🌏 Global – Markets & Macro  
D. 💍 Jewellery, Gold, Gems & Retail  
E. 🧩 Other Business & Consumer Trends  

Pick the section that best fits the MAIN focus of that group.

---------------- TASK 3 – OUTPUT FORMAT (HTML ONLY) ----------------
For each section you use, output:

<h2>SECTION TITLE</h2>
<div class="section">

  <div class="story">
    <h3>
      <a href="MAIN_LINK" target="_blank">MAIN HEADLINE (Source)</a>
    </h3>

    <p><b>Summary:</b> 1–3 sentences in simple English, combining information inferred from
       the grouped titles ONLY. Do NOT invent numbers, dates or specific details that are not in the titles.</p>

    <!-- If group has more than 1 item -->
    <ul>
      <li><b>Also covered by:</b></li>
      <ul>
        <li>Source – <a href="LINK_2" target="_blank">LINK_2</a></li>
        <li>Source – <a href="LINK_3" target="_blank">LINK_3</a></li>
      </ul>
    </ul>
    <!-- If group has only 1 item, OMIT the "Also covered by" block entirely. -->

  </div>

  <!-- more <div class="story"> blocks, one per story group -->

</div>

---------------- RULES FOR MAIN HEADLINE ----------------
- Choose ONE item in the group whose headline best describes the event.
- Its link becomes MAIN_LINK.
- All other items in the group go under "Also covered by".

---------------- HARD CONSTRAINTS ----------------
- EVERY input item (each ID) MUST appear in exactly ONE story group.
- NO item may be omitted or silently dropped.
- NO item may appear in more than one group.
- Do NOT output the numeric IDs in the final HTML.
- Do NOT invent any URL or news.
- Do NOT output any text outside HTML tags.
- Do NOT output <html>, <head> or <body> tags.

Use ONLY information from titles and sources. No external knowledge.
Output MUST be valid HTML only. No markdown, no commentary.
"""

    response = client.responses.create(
        # 🔁 SWITCH MODEL HERE:
        # "gpt-4.1-mini"  -> cheaper
        # "gpt-4.1"       -> smarter grouping
        model="gpt-4.1",          # <--- try upgrading to this for better grouping
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
