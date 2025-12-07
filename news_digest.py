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

# Curated India-heavy + some global context (native RSS where possible)
# =======================
# 1. RSS SOURCES
# =======================

RSS_FEEDS = [
    # 🔥 Zerodha Pulse — BEST curated Indian market news
    "https://pulse.zerodha.com/feed/",

    # 🔥 Economic Times — Master business/economy feed
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",

    # 🔥 Livemint — Markets feed (clean & high signal)
    "https://www.livemint.com/rss/marketsRSS",

    # 🔥 Business Standard — Official latest feed
    "https://www.business-standard.com/rss/latest.rss",

    # 🔥 Indian Express — Business feed (clean, non-spammy)
    "https://indianexpress.com/section/business/feed/",
]


# Keep this moderate so we don't blow context
MAX_ITEMS = 70   # total items across all feeds


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines + summaries from all RSS feeds."""
    items = []
    PER_FEED_LIMIT = 6  # max items per feed

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.get("title", "Unknown Source")

        for entry in feed.entries[:PER_FEED_LIMIT]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # Truncate very long summaries so model can still read "inside"
            if len(summary) > 350:
                summary = summary[:350] + "..."

            items.append(
                {
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                }
            )

    # Global cap so we don't blow up context
    MAX_ITEMS = 80
    return items[:MAX_ITEMS]



def build_headlines_text(items):
    """
    Turn news items into a text block for the AI.
    We include source, title, summary, link.
    """
    lines = []
    for i, item in enumerate(items, start=1):
        summary = item["summary"]

        lines.append(f"{i}) [Source: {item['source']}]")
        lines.append(f"   Title: {item['title']}")
        if summary:
            lines.append(f"   Summary: {summary}")
        if item["link"]:
            lines.append(f"   Link: {item['link']}")
        lines.append("")  # blank line

    text = "\n".join(lines)

    # Safety cap on size to avoid context errors
    if len(text) > 12000:
        text = text[:12000]
    return text



# =======================
# 3. CALL OPENAI – DIGEST GENERATION
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - read headlines + summaries
    - pick & club important business/economy/markets/jewellery stories
    - group into sections
    - output clean HTML only
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = """
You are an Indian business & markets analyst.

Below is a list of items from multiple business news sites.
Each has: [Source], Title, Summary, Link.
Use ONLY these items. Do NOT invent any story or URL.

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

If you are not sure whether a story has business impact, INCLUDE it. Err on the side of including more.

Ignore only:
- pure crime, gossip, celebrity, sports, weather, AQI, environment
  when the summary clearly has NO business/economic link.

---------------- MERGING ----------------
If multiple items are clearly about the same underlying event (same company, same decision, same policy move):
- Merge them into ONE story.
- Use the clearest headline as the title.
- Use summaries to enrich the bullets.

Aim for about 25–35 final stories (after merging).
If there are fewer distinct stories, output as many as exist.
Do NOT invent extra stories.

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
  diamonds, gems, bullion, hallmarking, or jewellery retailers. Otherwise, omit this section.

---------------- STORY FORMAT (HTML) ----------------
For EACH story, output EXACTLY this structure:

<div class="story">
  <h3>HEADLINE (Source)</h3>
  <ul>
    <li><b>What’s happening:</b> one short sentence summarising the key fact or outcome, ADDING detail beyond the headline. Do NOT repeat the headline wording.</li>
    <li><b>Why it’s happening:</b> one short sentence explaining the main driver or cause, using information from the summary (e.g. policies, demand, earnings, regulations, global trends).</li>
    <li><b>Why it matters (for business/markets):</b> one short sentence explaining who is affected (e.g. which investors, sectors, companies, consumers) and whether the impact is likely positive, negative, or uncertain.</li>
    <p><b>Impact:</b> POSITIVE / NEGATIVE / MIXED / UNCERTAIN (choose one word).</p>
  </ul>
  <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
</div>

Extra rules for style:
- "What’s happening" must NOT just restate the title; it should include at least one concrete detail (number, direction, timeframe, or sector) taken from the summary.
- "Why it’s happening" should focus on causes: policy decisions, demand/supply changes, global cues, company strategy, investor behaviour, etc.
- "Why it matters" should always mention impact on at least one of: investors, the economy, a sector, a company type (e.g. banks, exporters, IT), or consumers.


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
        model="gpt-4o-mini",  # if you can, upgrade this to "gpt-4.1" for even better quality
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
