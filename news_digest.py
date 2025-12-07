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

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=site:business-standard.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:economictimes.indiatimes.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:hindustantimes.com+business&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:moneycontrol.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:businesstoday.in&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:livemint.com&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=site:indianexpress.com+business&hl=en-IN&gl=IN:en",
    "https://news.google.com/rss/search?q=site:thehindubusinessline.com&hl=en-IN&gl=IN:en",
]

# Keep this conservative so we don't blow context
MAX_ITEMS = 60   # total items across all feeds


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines + summaries from all RSS feeds."""
    items = []
    PER_FEED_LIMIT = 10  # max per feed

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.get("title", "Unknown Source")

        for entry in feed.entries[:PER_FEED_LIMIT]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if not title:
                continue

            # Truncate very long summaries to save space but keep "reason" context
            if len(summary) > 400:
                summary = summary[:400] + "..."

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
    We include: source, title, summary, link.
    Also enforce an overall character cap to avoid context overflow.
    """
    lines = []
    char_limit = 12000  # hard cap on total text length
    current_len = 0

    for i, item in enumerate(items, start=1):
        block_lines = [
            f"{i}) [Source: {item['source']}]",
            f"   Title: {item['title']}",
        ]
        if item["summary"]:
            block_lines.append(f"   Summary: {item['summary']}")
        if item["link"]:
            block_lines.append(f"   Link: {item['link']}")
        block_lines.append("")  # blank line

        block_text = "\n".join(block_lines)
        if current_len + len(block_text) > char_limit:
            break

        lines.append(block_text)
        current_len += len(block_text)

    return "\n".join(lines)


# =======================
# 3. CALL OPENAI – DIGEST GENERATION
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - read headlines + summaries (for better 'reason' bullets)
    - pick & club important business/economy/markets/jewellery stories
    - group into sections
    - output clean HTML only
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = """
You are an Indian business & markets analyst.

Below is a list of items from multiple business news sites.
Each item has: [Source], Title, Summary and Link.

Use ONLY this input. Do NOT invent any story or URL.

INPUT HEADLINES:
{headlines_text}

---------------- WHAT TO INCLUDE ----------------
Select stories that clearly relate to:
- business, companies, sectors, earnings, funding, IPOs, M&A
- Indian macroeconomy: GDP, inflation, RBI, fiscal, trade, budget
- markets: stocks, bonds, commodities, FX, indices, yields
- policy/politics ONLY when it clearly affects business, economy or markets
- tech/startups/consumer trends with a clear business impact
- jewellery industry: gold, silver, diamonds, gems, bullion, hallmarking, jewellery retail, supply/demand

Ignore:
- crime, generic politics, celebrity gossip, sports, lifestyle, weather, air quality, environment
  unless the summary clearly shows a direct business/market/jewellery impact.

---------------- MERGING ----------------
If multiple items are clearly about the same underlying event (same company, same decision, same policy move):
- Merge them into ONE story.
- Use the clearest headline as the title.
- Use the summaries to deduplicate and enrich your bullets.

Aim for about 30–40 final stories (after merging).
If there are fewer distinct stories, output what you have.
Never invent extra stories.

---------------- SECTIONS ----------------
Group stories into these sections:

A. 🇮🇳 India – Economy & Markets
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
C. 🌏 Global – Markets & Macro
D. 💍 Jewellery Industry (India & Global)

Rules:
- Each story goes into exactly ONE section.
- If no story fits a section, omit that section.
- For the Jewellery section, only include stories where the title or summary clearly mentions jewellery, gold, silver,
  diamonds, gems, bullion, hallmarking, or jewellery retailers. Otherwise, leave this section out.

---------------- STORY FORMAT (HTML) ----------------
For EACH story, output EXACTLY this structure:

<div class="story">
  <h3>HEADLINE (Source)</h3>
  <ul>
    <li><b>What’s happening:</b> one short sentence describing the news.</li>
    <li><b>Why it’s happening:</b> one short sentence explaining the main driver or cause, using the summary.</li>
    <li><b>Why it matters (for business/markets):</b> one short sentence, very simple and concrete.</li>
  </ul>
  <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
</div>

- Use simple language (as if to a smart 15-year-old).
- Each bullet must be one short sentence (no long paragraphs).
- For each story, pick ONE real link from the input. Never invent or edit URLs.

---------------- OVERALL HTML STRUCTURE ----------------
For each section you actually use, output:

<h2>SECTION TITLE</h2>
<div class="section">
  ...many <div class="story"> blocks...
</div>

Do NOT output <html>, <head> or <body> tags.
Do NOT output any plain text outside HTML tags.

---------------- EXTRA SECTIONS AT THE END ----------------
After all news sections, append these two sections (also HTML):

<h2>💡 Monetizable Idea of the Day</h2>
<div class="section">
  <div class="story">
    <h3>IDEA TITLE</h3>
    <ul>
      <li><b>What it is:</b> one-sentence explanation.</li>
      <li><b>Why this opportunity exists now:</b> one sentence linked to current business or tech trends.</li>
      <li><b>How to execute:</b> 3–5 simple steps one person with low capital can follow.</li>
      <li><b>Example:</b> a realistic example of someone doing something similar.</li>
    </ul>
  </div>
</div>

<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> clear, simple definition.</li>
      <li><b>Why it works:</b> one-sentence psychological or business reason.</li>
      <li><b>How to apply:</b> 2–3 short, practical steps the reader can use today.</li>
    </ul>
  </div>
</div>

Output ONLY valid HTML as described. No markdown, no commentary.
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
