import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import feedparser
import pytz
from openai import OpenAI


# =======================
# 1. RSS SOURCES
# =======================

# Curated list: Indian business-heavy via Google News domain search
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=site:business-standard.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:economictimes.indiatimes.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:hindustantimes.com+business&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:moneycontrol.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:businesstoday.in&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:livemint.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:indianexpress.com+business&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:thehindubusinessline.com&hl=en-IN&gl=IN&ceid=IN:en",
]

# Upper limit of headlines to send to AI in one batch
MAX_ITEMS = 100


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines from all RSS feeds."""
    items = []

    PER_FEED_LIMIT = 10  # how many items to take from each feed

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.get("title", "Unknown Source")

        for entry in feed.entries[:PER_FEED_LIMIT]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if not title:
                continue

            items.append(
                {
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                }
            )

    # Hard cap so we don't blow up tokens
    return items[:MAX_ITEMS]


def build_headlines_text(items):
    """
    Turn news items into a text block that is easy for the AI to read.
    We include source, title, summary, link.
    """
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}) [Source: {item['source']}]")
        lines.append(f"   Title: {item['title']}")
        if item["summary"]:
            lines.append(f"   Summary: {item['summary']}")
        if item["link"]:
            lines.append(f"   Link: {item['link']}")
        lines.append("")  # blank line
    return "\n".join(lines)


# =======================
# 3. CALL OPENAI – DIGEST GENERATION
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - see up to MAX_ITEMS headlines from multiple Indian business feeds
    - pick and club the most important stories
    - group into sections
    - output clean HTML (no <html>/<body>, just inner content)
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = """
You are an expert Indian business & markets analyst.

You will receive a list of headlines and summaries from multiple Indian and global business news sources.

INPUT HEADLINES:
{headlines_text}

-----------------------------------------------------
YOUR TASK
-----------------------------------------------------

1) Select relevant business/economy/markets stories
Include stories related to:
- Indian macroeconomy (GDP, inflation, RBI, rates, trade, fiscal policy)
- Markets (stocks, bonds, commodities, FX, indices, yields)
- Business, corporate updates, sectors, earnings, funding, M&A, IPOs
- Policy or politics only when it has clear economic or business impact
- Tech, startups, consumer/business trends, wealth, personal finance
- Global news with implications for India
- Jewellery industry (retail, gold, pricing, imports, supply chain, demand)

IGNORE:
- Pure politics with no economic effect
- Crime, weather, celebrity lifestyle, sports (unless business-related)
- Entertainment content not tied to markets or money

-----------------------------------------------------
2) CLUB / MERGE DUPLICATE OR RELATED STORIES
If multiple headlines clearly refer to the same underlying event, you MUST:

- Merge them into one unified story
- Use the best headline as the title
- Combine important details from all related headlines inside the bullets
- Do NOT create multiple stories that are basically the same

Examples of items to club:
- Multiple stories about the same RBI policy update
- Repeated coverage of a single company’s earnings
- Several headlines about the same market move

-----------------------------------------------------
3) How many stories to generate
- After merging duplicates, aim for 35 to 55 stories total
- Err on the side of INCLUDING more stories if in doubt
- Do NOT output fewer than 30 stories unless there truly are not enough relevant items

-----------------------------------------------------
4) Group stories into these sections

A. 🇮🇳 India – Economy & Markets
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
C. 🌏 Global – Markets & Macro
D. 💍 Jewellery Industry (India & Global)

Rules:
- If a section has zero stories, you may omit it.
- Preferably keep at least a few stories inside each section.
- Each story must be placed under only one section.

-----------------------------------------------------
5) Format each story EXACTLY like this

<div class="story">
  <h3>HEADLINE (Source)</h3>
  <ul>
    <li><b>What’s happening:</b> ONE short sentence describing the event.</li>
    <li><b>Why it’s happening:</b> ONE short sentence explaining the main driver or cause.</li>
    <li><b>Why it matters (for business/markets):</b> ONE short sentence explained simply like to a smart 15-year-old.</li>
  </ul>
  <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
</div>

RULES FOR BULLETS:
- Each bullet MUST be a single short sentence.
- No long paragraphs.
- No jargon; use simple, crisp economic and business logic.

LINK RULE:
- Use the link from the input.
- If multiple input links were merged, choose the most useful one.

-----------------------------------------------------
6) HTML Structure Required
After grouping stories, output:

<h2>SECTION TITLE...</h2>
<div class="section">
  ...many <div class="story"> blocks...
</div>

You MUST output ONLY valid inner HTML.
Do NOT include <html>, <head> or <body> tags.

-----------------------------------------------------
7) ADD TWO FINAL SECTIONS

Monetizable Idea of the Day

<h2>💡 Monetizable Idea of the Day</h2>
<div class="section">
  <div class="story">
    <h3>IDEA TITLE</h3>
    <ul>
      <li><b>What it is:</b> one-sentence explanation.</li>
      <li><b>Why this opportunity exists now:</b> simple cause/effect linked to current news trends.</li>
      <li><b>How to execute:</b> 3–5 short, concrete steps.</li>
      <li><b>Example:</b> a realistic example of a business or person doing something similar.</li>
    </ul>
  </div>
</div>

Communication Upgrade of the Day

<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> clear, simple definition.</li>
      <li><b>Why it works:</b> psychological or business principle in ONE sentence.</li>
      <li><b>How to apply:</b> 2–3 short steps or examples the reader can use today.</li>
    </ul>
  </div>
</div>

-----------------------------------------------------
FINAL RULES:
-----------------------------------------------------
- Output ONLY the HTML described above.
- No prefaces, no explanations, no markdown, no notes.
- Keep everything tight, simple and business-focused.
"""

    # Safely inject headlines_text into the prompt
    prompt = prompt.format(headlines_text=headlines_text)

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    }
                ],
            }
        ],
    )

    return response.output_text


# =======================
# 4. SEND NICE HTML EMAIL
# =======================

def send_email(subject: str, digest_html: str):
    """Send a nicely formatted HTML email with the digest."""

    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    # IST timestamp for header inside email
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")

    # Wrap the AI HTML inside a nicer template
    html = f"""
    <html>
      <body style="margin:0; padding:0; background-color:#f5f5f5;">
        <div style="max-width:800px; margin:20px auto; font-family:Arial, sans-serif;">
          <div style="background:#ffffff; border-radius:12px; padding:20px 26px; box-shadow:0 2px 10px rgba(0,0,0,0.08);">
            
            <h1 style="margin:0 0 4px 0; font-size:22px; color:#111;">
              📊 Business News Digest
            </h1>
            <p style="margin:0; color:#777; font-size:12px;">
              Generated automatically on <b>{now_ist}</b> · Cause → Effect · Why it matters
            </p>

            <hr style="margin:16px 0; border:none; border-top:1px solid #eee;">

            <div style="font-size:14px; color:#222; line-height:1.6;">
              {digest_html}
            </div>

            <hr style="margin:20px 0; border:none; border-top:1px solid #eee;">

            <p style="font-size:11px; color:#999; margin:0;">
              🤖 This digest is auto-generated from multiple business news sources using AI.
              Treat it as a starting point, not investment advice.
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
# 5. MAIN
# =======================

def main():
    news_items = fetch_news()

    if not news_items:
        digest_html = "<p>No news items fetched. Check RSS feeds or code.</p>"
    else:
        headlines_text = build_headlines_text(news_items)
        digest_html = ask_ai_for_digest(headlines_text)

    # IST timestamp in subject
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Business News Digest – {now_ist}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
