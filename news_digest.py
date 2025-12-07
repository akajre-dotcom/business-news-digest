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

# Curated list: India-heavy + some global context
RSS_FEEDS = [
    # --- Indian: Livemint ---
    "https://www.livemint.com/rss/newsRSS",
    "https://www.livemint.com/rss/companiesRSS",
    "https://www.livemint.com/rss/marketsRSS",
    "https://www.livemint.com/rss/industryRSS",
    "https://www.livemint.com/rss/moneyRSS",
    "https://news.google.com/rss/search?q=site:moneycontrol.com+jewellery",

    # --- Indian: Business Standard ---
    "https://www.business-standard.com/rss/latest.rss",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.business-standard.com/rss/companies-101.rss",
    "https://www.business-standard.com/rss/economy-102.rss",
    "https://www.business-standard.com/rss/finance-103.rss",

    # --- Indian: Economic Times (main + economy) ---
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    "https://economictimes.indiatimes.com/rssfeeds/1373380680.cms",  # Economy

    # --- Global: Reuters (business + markets + economy) ---
    "http://feeds.reuters.com/reuters/businessNews",
    "http://feeds.reuters.com/reuters/INbusinessNews",
    "http://feeds.reuters.com/reuters/globalmarketsNews",
    "http://feeds.reuters.com/news/economy",
]

MAX_ITEMS = 100  # upper limit of headlines to send to AI in one batch


# =======================
# 2. FETCH NEWS
# =======================

def fetch_news():
    """Fetch recent headlines from all RSS feeds."""
    items = []

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.get("title", "Unknown Source")

        # Take first few items from each feed (limit: 5)
        for entry in feed.entries[:5]:
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
# 3. CALL OPENAI – BETTER CONTENT
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - see up to 100 headlines from multiple feeds
    - pick ~30 of the most important business/economy/markets/jewellery stories
    - try to cover all sections and sources
    - output clean HTML (no <html>/<body>, just inner content)
    """

    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = f"""
You are an expert business & markets analyst.

You will receive a list of headlines with source, summary and links.
These are mostly India + global business news.

INPUT HEADLINES:
{headlines_text}

TASK:

1) From these, select stories that are related to business/economy/markets:
   - macroeconomy (GDP, inflation, RBI, Fed, rates, trade, fiscal, deficits)
   - markets (stocks, bonds, commodities, FX, indices, yields)
   - business policy & regulation (tax, customs, trade, FDI, industry policy)
   - corporate & sectors (earnings, expansions, capacity, M&A, capex)
   - startups, funding, IPOs, exits
   - global business events that affect markets or Indian economy
   - Indian jewellery business, industry, gold, supply chain, retail and sales in jewellery

   IGNORE:
   - generic politics and elections unless they directly affect economy/business
   - social issues, crime, human interest, environment unless immediate business impact
   - generic editorials without concrete economic or business implication

   COVERAGE & SIZE RULES:
   - You are seeing up to 100 stories from many different [Source: ...] feeds.
   - From these, you MUST select BETWEEN 25 AND 30 stories in total.
   - Never output fewer than 25 stories unless there genuinely are not enough relevant items.
   - For each distinct [Source: ...] in the input, TRY to include at least one good story from that source, if any exist.
   - Distribute stories across the sections below so that, where possible, EACH section has AT LEAST 5 stories.
     If a section truly has fewer relevant stories, fill other sections more.
   - Prioritise:
     1) big macro / policy / market moves,
     2) key corporate / sector / funding / IPO updates,
     3) important global events,
     4) jewellery industry news (India + global).

2) Group selected stories into up to 4 sections (you can skip a section ONLY if it has zero relevant stories):

   A. 🇮🇳 India – Economy & Markets
   B. 🇮🇳 India – Corporate, Sectors, Startups & Deals
   C. 🌏 Global – Markets & Macro
   D. 💍 Jewellery Industry (India & Global)

3) For EACH story, output in this HTML structure:

   <div class="story">
     <h3>HEADLINE (Source)</h3>
     <ul>
       <li><b>What’s happening:</b> short, clear description of the news in 1–2 lines.</li>
       <li><b>Why it’s happening:</b> the main drivers, decisions, or forces behind this.</li>
       <li><b>Why it matters (for business/markets):</b> explain in very simple terms like to a smart 15-year-old, focusing on impact to economy, sectors, companies, investors, or policy.</li>
     </ul>
     <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
   </div>

Use the "Link:" field in the input as the href for the “Read more →” link.
If no link is available, omit that line.

4) Output valid HTML ONLY, with this structure:

   <h2>SECTION TITLE...</h2>
   <div class="section">
      ...multiple <div class="story"> blocks...
   </div>

RULES:
- Do NOT include <html>, <head>, <body> tags.
- Do NOT write anything outside these sections.
- Be concise but insightful, avoid buzzwords.
"""

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

    # This returns the entire text output as a single string
    return response.output_text
5) AFTER the 4 news sections, append two additional AI-generated sections:

--------------------------------------------------------
📌 **SECTION: 1 Monetizable Idea of the Day**
Provide ONE simple, actionable money-making idea based on:
- current business trends,
- opportunities emerging from the news,
- gaps in consumer behavior,
- AI/tech tools,
- jewellery industry trends,
- global patterns.

Make it:
- easy to understand,
- executable by 1 person with minimal/zero money,
- specific (not generic advice),
- with 3–5 concrete steps.

Format:

<h2>💡 Monetizable Idea of the Day</h2>
<div class="section">
  <div class="story">
    <h3>IDEA TITLE</h3>
    <ul>
      <li><b>What it is:</b> brief explanation.</li>
      <li><b>Why this opportunity exists now:</b> simple cause/effect logic.</li>
      <li><b>How to execute:</b> 3–5 steps.</li>
      <li><b>Example:</b> 1 real or realistic business already doing this.</li>
    </ul>
  </div>
</div>

--------------------------------------------------------
📌 **SECTION: 1 Communication Upgrade of the Day**
Give ONE powerful communication technique that makes someone:
- better at negotiation,
- clearer in speech,
- better at leadership communication,
- better at sales/persuasion,
- better at writing simple business English.

Keep it:
- short,
- highly practical,
- something the reader can use immediately.

Format:

<h2>🗣 Communication Upgrade of the Day</h2>
<div class="section">
  <div class="story">
    <h3>SKILL NAME</h3>
    <ul>
      <li><b>What it is:</b> simple definition.</li>
      <li><b>Why it works:</b> psychological/business principle.</li>
      <li><b>How to apply:</b> 2–3 steps or examples.</li>
    </ul>
  </div>
</div>



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
