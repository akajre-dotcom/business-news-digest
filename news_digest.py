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

MAX_ITEMS_PER_FEED = 15   # ⬅️ smaller, balanced per feed
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
# 4. CALL OPENAI – CLUSTER, SUMMARISE, ADD GROWTH SECTIONS
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Calls OpenAI to:
    - Filter to serious business/economic news
    - Pick a small set of high-impact, diverse stories
    - Use at most 1 story per company/theme
    - Output short, clickable summary-only HTML
    - Append 4 personal-growth sections
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()

    prompt = f"""
You are an expert business journalist and senior newsroom editor. Now you have to create front page of todays of news paper, mean most important news only

You receive a flat list of news items from multiple business, finance, markets, industry, and jewellery RSS feeds.
Each item has: numeric ID, [Source], Title, Link.

INPUT ITEMS:
{headlines_text}


==============================================================
STEP 0 – PROFESSIONAL NEWSROOM FILTER
==============================================================

Filter headlines STRICTLY — keep ONLY serious business/economic content.

EXCLUDE completely (do NOT mention or summarise these):
- Celebrity / OTT / entertainment / gossip.
- Crime/court drama unless it clearly affects a business, company, sector, or market.
- Viral videos, outrage, memes, human-interest odd stories.
- Lifestyle, travel pieces, festivals, weather.
- Pure politics with no business, market, or policy consequence.
- Local accidents or general news with no corporate or macro impact.

KEEP ONLY IF the story clearly affects:
- Companies, sectors, competition, governance, earnings, strategy.
- Financial markets: stocks, bonds, commodities, currencies, crypto.
- RBI / central bank / regulators / taxation / policy changes.
- Macro indicators: GDP, inflation, trade, fiscal.
- Startups, funding, IPOs, acquisitions, PE/VC.
- Gold, jewellery, gems / diamond retail trends with commercial impact.

If relevance is not obvious → EXCLUDE it.


==============================================================
STEP 1 – SELECT DISTINCT, HIGH-IMPACT STORIES
==============================================================

From the filtered headlines, select a small, *diverse* set of stories.

HARD LIMITS:
- You MUST output AT MOST 15 news stories in total (across all sections).
- For any single company / instrument / crisis / theme,
  you may output AT MOST 1 summary in the entire digest.

This means:
- If there are 15 headlines about the same news,
  you MUST mentally combine them and output JUST ONE summary for that topic.
- If there are many headlines about the same macro topic (e.g. a single RBI
  liquidity decision), output at most one well-phrased summary.
- Prioritise breadth and variety over completeness.

PRIORITISE:
- Systemic impact (economy, markets, RBI, major policy).
- Big corporate moves (M&A, funding, IPOs, major sector shifts).
- Clear investor / sector impact.
- Jewellery / gold where there is real business relevance.

Do NOT try to cover every filtered headline.  
Pick the ~10 most important and distinct stories.


==============================================================
STEP 2 – ASSIGN EACH STORY TO ONE SECTION
==============================================================

Each chosen story must go to EXACTLY ONE of:

A. 🇮🇳 India – Economy, Markets, Corporate, Sectors, Startups & Deal  
B. 🌏 Global – Economy, Markets, Corporate, Sectors, Startups & Deal  
C. 💍 Jewellery, Gold, Gems & Retail  
D. 🧩 Other Business related & Consumer Trends  
E. 📈 Stock Market – Shares, Prices, Analysis  

Choose the section that best fits the main focus of the story.


==============================================================
STEP 3 – OUTPUT FORMAT (STRICT HTML ONLY, CLICKABLE SUMMARY)
==============================================================

For each section you actually use, output:

<h2>SECTION TITLE</h2>
<div class="section">

  <div class="story">
    <p>
      <a href="MAIN_LINK" target="_blank">
        <b>Summary:</b>
        ONE short sentence in clean, neutral English describing
        what happened and why it matters.
      </a>
      <span> (Source: MAIN_SOURCE)</span>
    </p>
  </div>

  <!-- more <div class="story"> blocks -->

</div>

SUMMARY RULES:
- The summary itself must be clickable (inside the <a> tag).
- Do NOT just repeat the headline; add value:
  - mention the type/direction of change and who/what is affected (sector, investors, policy, company).
- Use ONLY what can be inferred from the titles (no invented numbers, quotes, or dates).
- Each summary MUST be exactly ONE sentence.


==============================================================
AFTER ALL NEWS SECTIONS — ADD THESE SEVEN DAILY VALUE-UPGRADES
==============================================================

Use minimum words. Explanations must follow first-principles thinking:
- Define the core idea.
- Explain why it works.
- Give 2–3 extremely practical application steps.
- No fluff, no quotes, no stories unless they add clear value.

Very important:
- You do NOT have live data.
- For all sections below, choose examples that are timeless / generally true.
- Do NOT mention “yesterday”, dates, or specific recent events.
- If you mention a CEO, company, or book, choose well-known, high-signal ones.

1️⃣ 🗣 Communication Upgrade of the Day
--------------------------------------
<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> Short, first-principles definition.</li>
      <li><b>Why it works:</b> One sentence explaining the underlying psychological or logical mechanism.</li>
      <li><b>How to apply:</b> 2–3 direct, real-world steps anyone can use today.</li>
    </ul>
  </div>
</div>

2️⃣ 🧠 Mental Model of the Day
------------------------------
<h2>🧠 Mental Model of the Day</h2>
<div class="section">
  <div class="story">
    <h3>MENTAL MODEL NAME</h3>
    <ul>
      <li><b>Core principle:</b> One-line explanation of the idea from first principles.</li>
      <li><b>Why it matters:</b> One sentence on how it improves decision-making.</li>
      <li><b>How to use:</b> 2–3 short, practical steps or scenarios.</li>
    </ul>
  </div>
</div>

3️⃣ 🧩 Cognitive Bias of the Day
-------------------------------
<h2>🧩 Cognitive Bias of the Day</h2>
<div class="section">
  <div class="story">
    <h3>BIAS NAME</h3>
    <ul>
      <li><b>What it is:</b> One-sentence definition.</li>
      <li><b>Why it happens:</b> First-principles explanation of the brain mechanism behind the bias.</li>
      <li><b>How to counter it:</b> 2–3 actionable, simple steps.</li>
    </ul>
  </div>
</div>

4️⃣ 📘 1-Page Book Summary of the Day
-------------------------------------
<h2>📘 1-Page Book Summary of the Day</h2>
<div class="section">
  <div class="story">
    <h3>BOOK TITLE (Author)</h3>
    <ul>
      <li><b>Core idea:</b> One powerful sentence summarising the book’s main argument.</li>
      <li><b>Key principles:</b> 3–4 bullets, each expressing a first-principles insight.</li>
      <li><b>How to apply:</b> 2–3 practical actions based on the book’s ideas.</li>
    </ul>
  </div>
</div>

Rules for choosing the book:
- Choose a widely known, high-impact non-fiction book in business, investing,
  decision-making, psychology, or careers (e.g., no obscure or niche titles).
- Do NOT claim the book was released “recently” or “yesterday”.

5️⃣ 🏢 What Top CEOs Are Saying
-------------------------------
<h2>🏢 What Top CEOs Are Saying</h2>
<div class="section">
  <div class="story">
    <h3>COMPANY / CEO</h3>
    <ul>
      <li><b>Main message:</b> One-line summary of a typical strategic or cultural message this CEO is known for.</li>
      <li><b>Reasoning:</b> One sentence on the underlying principle or strategy behind that message.</li>
      <li><b>Implication:</b> One sentence on what it means for employees, investors, or customers.</li>
    </ul>
  </div>
</div>

Rules for this section:
- Pick a well-known CEO of a major global or Indian company.
- Use a timeless, representative message (e.g., focus on customers, long-term thinking),
  not a “yesterday” quote.
- Do NOT mention dates, “yesterday”, or specific quarterly calls.

6️⃣ 🎯 Decision-Making Model of the Day
---------------------------------------
<h2>🎯 Decision-Making Model of the Day</h2>
<div class="section">
  <div class="story">
    <h3>MODEL NAME</h3>
    <ul>
      <li><b>Principle:</b> One-line first-principles definition.</li>
      <li><b>Why it works:</b> One sentence explaining the mechanism.</li>
      <li><b>How to use:</b> 2–3 simple steps.</li>
    </ul>
  </div>
</div>

7️⃣ 🤝 Negotiation Model of the Day
-----------------------------------
<h2>🤝 Negotiation Model of the Day</h2>
<div class="section">
  <div class="story">
    <h3>MODEL NAME</h3>
    <ul>
      <li><b>What it is:</b> Short definition focusing on incentives and first principles.</li>
      <li><b>Why it works:</b> One sentence explaining the psychology or logic behind it.</li>
      <li><b>How to apply:</b> 2–3 methods usable in real workplace or business negotiations.</li>
    </ul>
  </div>
</div>


==============================================================
NON-NEGOTIABLE OUTPUT RULES
==============================================================

- Use ONLY information from the input titles for news summaries.
- You may drop less-important headlines completely to respect
  the 10-story and 1-story-per-theme limits.
- Do NOT invent URLs.
- Do NOT output numeric IDs.
- Output must be PURE HTML.
- Do NOT output <html>, <head>, or <body> tags.
- The four value-add sections at the end are MANDATORY.

End of instructions.
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        max_output_tokens=3500,  # more room so it doesn't cut off
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
