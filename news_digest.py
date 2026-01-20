import os
import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import List, Dict
import time
import random

import feedparser
import pytz
from openai import OpenAI


# =======================
# 1. CONFIG
# =======================

RSS_FEEDS = [
    # World Gold Council, LBMA, Central Bank Gold (via Google News)
    "https://news.google.com/rss/search?q=World+Gold+Council+gold+demand&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=LBMA+gold+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=central+bank+gold+buying&hl=en-IN&gl=IN&ceid=IN:en",

    # Diamonds – Rough, Polished, Supply
    "https://news.google.com/rss/search?q=De+Beers+diamond+sales&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=ALROSA+diamond+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Rapaport+diamond+market&hl=en-IN&gl=IN&ceid=IN:en",

    # India Jewellery Manufacturing
    "https://news.google.com/rss/search?q=GJEPC+jewellery+export+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Surat+diamond+industry&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Jaipur+gems+industry&hl=en-IN&gl=IN&ceid=IN:en",

    # Middle East Jewellery & Gold Retail
    "https://news.google.com/rss/search?q=Dubai+gold+market+jewellery&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=UAE+jewellery+retail&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Saudi+Arabia+jewellery+luxury&hl=en-IN&gl=IN&ceid=IN:en",
]

MAX_ITEMS_PER_FEED = 15
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
    return text


# =======================
# 4. CALL OPENAI – 7 VALUE SECTIONS + NEWS FRONT PAGE
# =======================

def ask_ai_for_digest(headlines_text: str, digest_type: str) -> str:
    """
    Role-based Jewellery Industry Intelligence Digest
    Clean, non-repeating, CEO-grade
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()

    ROLE_INSTRUCTIONS = {
        "retailer": """
Focus on walk-in demand, sell-through, inventory rotation,
discounting pressure, and customer behaviour.
Explain in simple language a store owner understands.
""",
        "manufacturer": """
Focus on order flow, capacity utilisation, costs, labour,
working capital, and product mix decisions.
""",
        "exporter": """
Focus on US, Europe, and Middle East demand,
buyer behaviour, margins, and currency impact.
""",
        "miner": """
Focus on supply discipline, pricing power,
and downstream stress signals.
""",
        "trader": """
Focus on gold and silver price direction,
physical vs paper demand, and short-term risk.
""",
        "investor": """
Focus on market share shifts, balance sheet strength,
cycle positioning, and long-term winners vs traps.
"""
    }

    prompt = f"""
You are a senior jewellery-industry advisor mentoring promoters,
CEOs, and family business owners.

PRIMARY ROLE TODAY: {digest_type.upper()}

{ROLE_INSTRUCTIONS.get(digest_type, "")}

India is the core market.
Middle East, US, and Europe are analysed only for their impact on India or jewellery industry.

INPUT HEADLINES:
{headlines_text}

====================================================
FILTER RULES
====================================================
Keep ONLY news that affects jewellery economics.
Drop marketing, lifestyle, PR, celebrity, and generic politics.

====================================================
OUTPUT RULES
====================================================
- PURE HTML only (no <html>, <body>, <head>)
- Simple, clear language
- Explain what it means for business
- No invented numbers or quotes

====================================================
DIGEST STRUCTURE (SINGLE, FINAL)
====================================================

<h2>🔎 Executive Snapshot</h2>
<div class="section">
<ul>
<li>What changed today.</li>
<li>Why it matters.</li>
<li>Who benefits and who is under stress.</li>
</ul>
</div>

<h2>🌍 Macro & Policy Drivers</h2>
<div class="section">
<ul>
<li>Interest rates, currencies, central banks.</li>
<li>Gold import/export duties and regulation.</li>
<li>Geopolitical or energy-linked demand drivers.</li>
</ul>
</div>

<h2>🪙 Bullion Intelligence – Gold & Silver</h2>
<div class="section">
<ul>
<li>Spot vs physical demand signals.</li>
<li>India local premium or discount.</li>
<li>UAE / GCC physical buying behaviour.</li>
</ul>
</div>

<h2>💎 Diamonds & Polki – Supply Chain Health</h2>
<div class="section">
<ul>
<li>Rough supply vs polished inventory.</li>
<li>Lab-grown vs natural diamond demand.</li>
<li>Polki and bridal jewellery signals.</li>
</ul>
</div>

<h2>🎨 Coloured Stones & High-Margin Niches</h2>
<div class="section">
<ul>
<li>Emerald, ruby, sapphire availability.</li>
<li>Luxury and bespoke demand trends.</li>
</ul>
</div>

<h2>🇮🇳 India vs 🇦🇪 Middle East Demand</h2>
<div class="section">
<ul>
<li>India: weddings, rural vs urban demand.</li>
<li>ME: tourism-driven and oil-linked spending.</li>
</ul>
</div>

<h2>🏢 Major Players – Strategic Moves</h2>
<div class="section">
<ul>
<li>Expansion, consolidation, or defensive moves.</li>
<li>Inventory or supply-side actions.</li>
</ul>
</div>

<h2>🏬 Retailer Deep Dive of the Day</h2>
<div class="section">
<ul>
<li>Profile and target customer.</li>
<li>Core strength.</li>
<li>Go-to-market strategy.</li>
<li>Competitive edge.</li>
</ul>
</div>

<h2>📦 Product & Sell-Through Intelligence</h2>
<div class="section">
<ul>
<li>Fast-moving categories.</li>
<li>Slow or stressed inventory.</li>
<li>Trade-up vs trade-down behaviour.</li>
</ul>
</div>

<h2>📊 Margin & Inventory Stress Signals</h2>
<div class="section">
<ul>
<li>Where margins are expanding or compressing.</li>
<li>Which segment is under pressure.</li>
</ul>
</div>

<h2>📰 Editorial Must-Read</h2>
<div class="section">
<ul>
<li>One article worth deep attention.</li>
<li>Main business lesson.</li>
</ul>
</div>

<h2>🗣️ Industry Voice of the Day</h2>
<div class="section">
<ul>
<li>What industry insiders believe.</li>
<li>What behaviour this signals.</li>
</ul>
</div>

<h2>📐 Trend Classification</h2>
<div class="section">
<ul>
<li>Trend observed.</li>
<li>Fad, cyclical, or structural.</li>
<li>What to do about it.</li>
</ul>
</div>

<h2>🎯 Strategic Question of the Day</h2>
<div class="section">
<p>
If you were running a jewellery business today,
what decision deserves serious thinking — and why?
</p>
</div>

====================================================
HARD RULES
====================================================
- Use ONLY headline-based information
- No hype, no marketing language
- Prefer uncomfortable truths
- Rotate retailers and experts (no repetition within 14 days)

End of instructions.
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        temperature=0.35,
        max_output_tokens=3200,
    )

    return response.output_text.strip()




# =======================
# 5. SEND NICE HTML EMAIL (WITH HEADER IMAGE)
# =======================

def send_email(subject: str, digest_html: str):
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")

    # 👉 Replace these with real copyright-free image URLs
    # from Unsplash / Pexels etc.
    header_images = [
        "https://your-image-host.com/business-header-1.jpg",
        "https://your-image-host.com/markets-header-2.jpg",
        "https://your-image-host.com/strategy-header-3.jpg",
    ]
    selected_image = random.choice(header_images)

    header_img_html = ""
    if selected_image:
        header_img_html = f"""
        <div style="margin:0 -26px 16px -26px;">
          <img src="{selected_image}"
               alt="Business & markets"
               style="width:100%; max-height:220px; object-fit:cover; border-radius:12px 12px 0 0; display:block;">
        </div>
        """

    html = f"""
    <html>
      <body style="margin:0; padding:0; background-color:#f5f5f5;">
        <div style="max-width:800px; margin:20px auto; font-family:Arial, sans-serif;">
          <div style="background:#ffffff; border-radius:12px; padding:20px 26px; box-shadow:0 2px 10px rgba(0,0,0,0.08);">

            {header_img_html}

            <h1 style="margin:0 0 4px 0; font-size:22px; color:#111;">
              📊 7 Daily Value Upgrades & Business News Digest
            </h1>
            <p style="margin:0; color:#777; font-size:12px;">
              Generated automatically on <b>{now_ist}</b>
            </p>

            <hr style="margin:16px 0; border:none; border-top:1px solid #eee;">

            <div style="font-size:14px; color:#222; line-height:1.6;">
              {digest_html}
            </div>

            <hr style="margin:20px 0; border:none; border-top:1px solid #eee;">

            <p style="font-size:11px; color:#999; margin:0;">
              🤖 This digest is auto-generated from multiple business news RSS feeds using AI.
              Headlines are filtered for business relevance, condensed, and grouped by theme.
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
