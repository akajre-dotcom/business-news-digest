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

# Indian business-heavy via Google News domain search
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

# Keep this moderate so we don't hit context limits
MAX_ITEMS = 80  # total items across all feeds


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines from all RSS feeds."""
    items = []
    PER_FEED_LIMIT = 12  # per feed

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

    return items[:MAX_ITEMS]


def build_headlines_text(items):
    """
    Turn news items into a compact text block for the AI.
    To save tokens, we use only source, title, link.
    """
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}) [Source: {item['source']}]")
        lines.append(f"   Title: {item['title']}")
        if item["link"]:
            lines.append(f"   Link: {item['link']}")
        lines.append("")
    text = "\n".join(lines)

    # Safety cap on characters to avoid context overflow
    if len(text) > 12000:
        text = text[:12000]
    return text


# =======================
# 3. CALL OPENAI – DIGEST GENERATION
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - read many headlines from business sources
    - pick and club important stories
    - group into sections
    - output clean HTML (no <html>/<body>, just inner content)
    - never invent stories
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = """
You are an expert Indian business & markets analyst.

Below is a list of headlines from multiple business news sites.
This list is your ONLY source of truth. Do NOT invent any stories or links.

INPUT HEADLINES:
{headlines_text}

---------------- TASK ----------------
1) Select stories that clearly relate to:
- business, companies, sectors, earnings, funding, IPOs, M&A
- Indian macroeconomy (GDP, inflation, RBI, fiscal, trade)
- markets (stocks, bonds, commodities, FX, indices, yields)
- policy/politics only when it has clear economic or business impact
- tech/startup/consumer trends with a money or business angle
- jewellery industry: gold, silver, diamonds, gems, jewellery retail, hallmarking, bullion, supply chain, demand

Ignore:
- crime, generic politics, celebrity/lifestyle, sports, weather, air quality, general environment
  unless there is a direct business/market/jewellery angle.

2) CLUB / MERGE duplicates:
- If multiple headlines are clearly about the same event (e.g., one company, one RBI move, one IPO),
  merge them into ONE story.
- Use the clearest headline as the title and combine useful details into the bullets.
- Do NOT output several separate stories that say almost the same thing.

3) Number of stories:
- After merging, aim for 30–45 stories.
- If you have fewer distinct stories, output what you have.
- Do NOT invent extra stories to hit the target.

4) Sections:
Group stories into these sections:

A. 🇮🇳 India – Economy & Markets
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
C. 🌏 Global – Markets & Macro
D. 💍 Jewellery Industry (India & Global)

Rules:
- Each story goes into exactly ONE section.
- If a section has no relevant stories, omit that section.
- For the Jewellery section, only include stories that clearly mention jewellery, gold, silver, diamonds,
  gems, hallmarking, bullion or jewellery retailers. If there are none, omit this section.

5) Story format (STRICT HTML):

For each story, output exactly:

<div class="story">
  <h3>HEADLINE (Source)</h3>
  <ul>
    <li><b>What’s happening:</b> ONE short sentence describing the event.</li>
    <li><b>Why it’s happening:</b> ONE short sentence on the main driver or cause.</li>
    <li><b>Why it matters (for business/markets):</b> ONE short sentence, explained simply.</li>
  </ul>
  <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
</div>

Rules:
- Each bullet is just one short sentence (no long paragraphs).
- Use simple, clear language (imagine explaining to a smart 15-year-old).
- For each story, pick one real link from the input headlines. Never invent or modify URLs.

6) Overall HTML structure:

For each section you use, output ONLY:

<h2>SECTION TITLE</h2>
<div class="section">
  ...many <div class="story"> blocks...
</div>

Do NOT output <html>, <head> or <body> tags.
Do NOT output any plain text outside these tags.

7) Extra sections at the end (also in HTML):

Monetizable Idea of the Day:

<h2>💡 Monetizable Idea of the Day</h2>
<div class="section">
  <div class="story">
    <h3>IDEA TITLE</h3>
    <ul>
      <li><b>What it is:</b> one-sentence explanation.</li>
      <li><b>Why this opportunity exists now:</b> one sentence linked to current business or tech trends.</li>
      <li><b>How to execute:</b> 3–5 short, concrete steps that one person with low capital can follow.</li>
      <li><b>Example:</b> a realistic example of someone doing something similar.</li>
    </ul>
  </div>
</div>

Communication Upgrade of the Day:

<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> clear, simple definition.</li>
      <li><b>Why it works:</b> one sentence on the psychological or business principle.</li>
      <li><b>How to apply:</b> 2–3 short, practical steps or examples the reader can use today.</li>
    </ul>
  </div>
</div>

FINAL RULES:
- Use ONLY the HTML tags shown above.
- No markdown, no prose explanation, no text outside HTML.
- Do NOT invent any stories, facts, or links not present in the input headlines.
"""

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

    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")
    subject = f"Business News Digest – {now_ist}"

    send_email(subject, digest_html)


if __name__ == "__main__":
    main()
