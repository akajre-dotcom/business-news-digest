import os
import ssl
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from typing import List, Dict, Optional

import requests
import feedparser
from bs4 import BeautifulSoup
import pytz
from openai import OpenAI


# =======================
# 1. CONFIG
# =======================

# RSS sources (same as both scripts)
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

# Scraper / network settings (from working script)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSSNewsScraper/1.0; +https://example.com/bot)"
}
REQUEST_TIMEOUT = 15     # seconds
MAX_ITEMS_PER_FEED = 20  # how many articles per RSS feed to consider
MAX_ITEMS = 100           # global cap for newsletter (after de-dup + scraping)


# =======================
# 2. SCRAPING UTILITIES
# =======================

def fetch_html(url: str) -> Optional[str]:
    """Download raw HTML of a page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch page {url}: {e}")
        return None


def extract_main_text(html: str) -> str:
    """
    Simple text extractor:
    - Remove scripts/styles
    - Join all <p> tags
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if p)
    return text


def fetch_rss_items(feed_url: str, max_items: int = MAX_ITEMS_PER_FEED) -> List[Dict]:
    """
    Read items from an RSS feed and return list of dicts:
    {feed_url, feed_title, title, link, published, rss_summary}
    """
    print(f"[INFO] Reading RSS: {feed_url}")
    feed = feedparser.parse(feed_url)

    feed_title = feed.feed.get("title", feed_url)

    items: List[Dict] = []
    for entry in feed.entries[:max_items]:
        link = entry.get("link")
        if not link:
            continue

        item = {
            "feed_url": feed_url,
            "feed_title": feed_title,
            "title": entry.get("title", "").strip(),
            "link": link,
            "published": entry.get("published", "") or entry.get("updated", ""),
            "rss_summary": entry.get("summary", "").strip(),
        }
        items.append(item)

    print(f"[INFO] Found {len(items)} items in RSS feed: {feed_title}")
    return items


def collect_all_rss_articles(rss_feeds: List[str]) -> List[Dict]:
    """Collect all unique article links from all RSS feeds."""
    all_items: List[Dict] = []
    seen_links = set()

    for feed_url in rss_feeds:
        feed_items = fetch_rss_items(feed_url)
        for item in feed_items:
            link = item["link"]
            if link in seen_links:
                continue
            seen_links.add(link)
            all_items.append(item)

    print(f"\n[INFO] Total unique articles collected from RSS: {len(all_items)}")
    return all_items


# =======================
# 3. BUILD INPUT FOR DIGEST MODEL
# =======================

def fetch_news() -> List[Dict]:
    """
    Collect unique articles, scrape them, and return a list of simplified items:
    {source, title, summary, link}

    These items are what we feed into the digest LLM (via build_headlines_text).
    """
    articles = collect_all_rss_articles(RSS_FEEDS)

    items: List[Dict] = []
    for article in articles:
        if len(items) >= MAX_ITEMS:
            break

        url = article["link"]
        feed_title = article["feed_title"] or "Unknown Source"
        title = article["title"] or "(No title)"

        html = fetch_html(url)
        if html:
            text = extract_main_text(html).strip()
        else:
            # Fallback to RSS summary if page fetch fails
            text = article["rss_summary"]

        # If still empty, skip
        if not text:
            continue

        # Truncate for context safety
        if len(text) > 600:
            text_snippet = text[:600] + "..."
        else:
            text_snippet = text

        items.append(
            {
                "source": feed_title,
                "title": title,
                "summary": text_snippet,
                "link": url,
            }
        )

    print(f"[INFO] Prepared {len(items)} items for digest model (after scraping)")
    return items


def build_headlines_text(items: List[Dict]) -> str:
    """
    Turn news items into a text block for the AI.
    We include source, title, scraped summary snippet, link.
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
# 4. CALL OPENAI – DIGEST GENERATION
# =======================

def ask_ai_for_digest(headlines_text: str) -> str:
    """
    Ask OpenAI to:
    - read headlines + scraped summaries
    - pick & club important business/economy/markets/jewellery stories
    - group into sections
    - output clean HTML only
    """

    if "OPENAI_API_KEY" not in os.environ:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI()  # reads OPENAI_API_KEY from env

    prompt = """
You are an expert financial and business journalist writing for an Indian
audience, with a focus on jewellery, gold, gems, diamonds, and retail
(where relevant).

Read the article text below and write a clear, structured summary.

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

Aim for about 50–70 final stories (after merging).
If there are fewer distinct stories, output as many as exist. 

Also give me count in the end like read x number of stories form link 1 and so on, total stories was y, out of that z stories was unique. and giving out a no of stories.
Do NOT invent extra stories. Give proper statistics.

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
    <li><b>Why it’s happening:</b> one short sentence explaining the main driver or cause, using information from the summary (e.g. policy moves, demand/supply,macro trends, company strategy, global cues, regulations, etc.).</li>
    <li><b>Why it matters (for business/markets):</b> one short sentence explaining who is affected (e.g. which investors, sectors, companies, consumers, prices, demand, margins, consumer behaviour, risks, or opportunities) and whether the impact is likely positive, negative, or uncertain.</li>
    <p><b>Impact:</b> POSITIVE / NEGATIVE / MIXED / UNCERTAIN (choose one word).</p>
  </ul>
  <p><a href="LINK_FROM_INPUT" target="_blank">Read more →</a></p>
</div>

Extra rules for style:
- "What’s happening" must NOT just restate the title; it should include at least one concrete detail (number, direction, timeframe, or sector) taken from the summary.

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
""".format(
        headlines_text=headlines_text
    )

    response = client.responses.create(
        model="gpt-4.1",           # or "gpt-4.1-mini" if you want cheaper
        input=prompt,
        max_output_tokens=5000,    # keep large enough for full HTML
        temperature=0.3,
    )

    # Same style as your working script
    return response.output_text.strip()


# =======================
# 5. SEND NICE HTML EMAIL
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
# 6. MAIN
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
