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
MAX_ITEMS = 200


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines from all RSS feeds."""
    items = []

    PER_FEED_LIMIT = 20  # how many items to take from each feed

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
    - see up to MAX_ITEMS headlines from multiple feeds
    - pick and club the most important business/economy/markets/jewellery stories
    - never invent stories not present in the input
    - output STRICT HTML (no <html>/<body>, just inner content)
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = """
You are an expert Indian business & markets analyst.

You will receive a list of headlines and summaries from multiple Indian and global business news sources.

INPUT HEADLINES (this is your ONLY source of truth – do NOT invent anything):
{headlines_text}

-----------------------------------------------------
HARD CONSTRAINTS (MUST OBEY)
-----------------------------------------------------
- Every story you output MUST be directly based on one or more of the INPUT HEADLINES.
- You MUST NOT invent or add stories that are not present in the input.
- If a topic is not in the input, completely ignore it.
- Output MUST be valid HTML only, using the specified structure. No plain text outside HTML tags.

-----------------------------------------------------
1) Select relevant business/economy/markets stories
-----------------------------------------------------
Include stories related to:
- Indian macroeconomy (GDP, inflation, RBI, rates, trade, fiscal policy)
- Markets (stocks, bonds, commodities, FX, indices, yields)
- Business, corporate updates, sectors, earnings, funding, M&A, IPOs
- Policy or politics only when it has clear economic or business impact
- Tech, startups, consumer/business trends, wealth, personal finance
- Global news with implications for India
- Jewellery industry (retail, gold, silver, diamonds, gems, jewellery retailers, hallmarking, bullion, supply chain, demand)

IGNORE:
- Pure politics with no economic effect
- Crime, weather, air quality, general environment, celebrity lifestyle, sports (unless clearly business-related)
- Any content without a clear business, economic, markets or jewellery angle

-----------------------------------------------------
2) CLUB / MERGE DUPLICATE OR RELATED STORIES
-----------------------------------------------------
If multiple headlines clearly refer to the same underlying event, you MUST:

- Merge them into one unified story.
- Use the best headline as the title.
- Combine important details from all related headlines inside the bullets.
- Do NOT create multiple separate stories that say almost the same thing.

Examples of items to club:
- Multiple stories about the same RBI policy update.
- Repeated coverage of a single company’s earnings or IPO.
- Several headlines about the same market move or corporate event.

-----------------------------------------------------
3) Number of stories
-----------------------------------------------------
- After merging duplicates, aim for 40 to 60 stories total.
- If there are fewer distinct stories available, output as many as exist, but never fewer than 30 if you have 60+ input headlines.
- Err on the side of INCLUDING more stories if you are unsure.

-----------------------------------------------------
4) Sections
-----------------------------------------------------
Group stories into these sections:

A. 🇮🇳 India – Economy & Markets
B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
C. 🌏 Global – Markets & Macro
D. 💍 Jewellery Industry (India & Global)

Rules:
- Each story must go into exactly ONE section.
- If a section has zero relevant stories, omit that section entirely.
- JEWELLERY SECTION RULE:
  - Only include stories where the headline or summary clearly mentions jewellery, gold, silver, bullion, diamonds, gems, jewellery retailers, hallmarking or related industry terms.
  - If there are no such stories in the input, DO NOT create the Jewellery section at all.

-----------------------------------------------------
5) Story HTML format (STRICT)
-----------------------------------------------------
For EACH story, output HTML EXACTLY like this:

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
- No jargon; use simple, clear, concrete language.

LINK RULE:
- For each story, pick one URL from the input headlines that describe that story.
- Use that URL as the link in the “Read more →” line.
- Never make up or modify URLs.

-----------------------------------------------------
6) Overall HTML structure
-----------------------------------------------------
You MUST output ONLY this pattern (repeat for each section you use):

<h2>SECTION TITLE...</h2>
<div class="section">
  ...many <div class="story"> blocks...
</div>

- Do NOT include <html>, <head> or <body> tags.
- Do NOT add any text outside these <h2>, <div class="section">, <div class="story">, <ul>, <li>, <p>, <a>, <b>, <h3> tags.

-----------------------------------------------------
7) Extra Sections at the end
-----------------------------------------------------

After all news sections, append these two blocks IN HTML:

(1) Monetizable Idea of the Day

<h2>💡 Monetizable Idea of the Day</h2>
<div class="section">
  <div class="story">
    <h3>IDEA TITLE</h3>
    <ul>
      <li><b>What it is:</b> one-sentence explanation.</li>
      <li><b>Why this opportunity exists now:</b> simple cause/effect linked to current business or tech trends.</li>
      <li><b>How to execute:</b> 3–5 short, concrete steps that one person with low capital can follow.</li>
      <li><b>Example:</b> a realistic example of a business or person already doing something similar.</li>
    </ul>
  </div>
</div>

(2) Communication Upgrade of the Day

<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> clear, simple definition.</li>
      <li><b>Why it works:</b> one sentence explaining the psychological or business principle.</li>
      <li><b>How to apply:</b> 2–3 short steps or examples the reader can use today.</li>
    </ul>
  </div>
</div>

-----------------------------------------------------
FINAL RULES:
-----------------------------------------------------
- Output ONLY valid HTML as described above.
- Do NOT include any markdown, commentary, or text outside HTML tags.
- Do NOT invent any stories, numbers or links not present in the input.
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
