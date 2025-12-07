import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import feedparser
from openai import OpenAI


# 1. SETTINGS (you can change RSS feeds later)
RSS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",   # WSJ Markets
    "https://www.livemint.com/rss/markets",            # LiveMint Markets
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",  # Reuters business
]

MAX_ITEMS = 20  # how many headlines we send to the AI max


def fetch_news():
    """Fetch recent headlines from all RSS feeds."""
    items = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.get("title", "Unknown Source")
        for entry in feed.entries[:10]:  # take first 10 from each
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if title:
                items.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                })

    # cut to max items so prompt is not too long
    return items[:MAX_ITEMS]


def build_headlines_text(items):
    """Turn news items into a big text block for the AI."""
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}) [{item['source']}] {item['title']}")
        if item["summary"]:
            lines.append(f"   Summary: {item['summary']}")
        if item["link"]:
            lines.append(f"   Link: {item['link']}")
        lines.append("")  # blank line
    return "\n".join(lines)


def ask_ai_for_digest(headlines_text):
    """Call OpenAI to turn raw headlines into cause–effect digest."""
    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)

    prompt = f"""
You are an expert global business analyst.

Here are recent business & markets headlines and summaries:

{headlines_text}

TASK:
1. Pick the 7–12 most important stories (global + India).
2. For each chosen story, output in this exact format:

## Headline (Source)
• Cause:
• Effect:
• Why this matters: (simple explanation like to a smart 15-year-old, first-principles, 1–2 lines)

3. No jargon. No extra commentary outside this format.
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

    # Simple helper: this gives us the whole text in one go
    return response.output_text


def send_email(subject, body):
    """Send the digest via email using SMTP details from environment variables."""

    # These will come from GitHub secrets
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls(context=context)
        server.login(smtp_username, smtp_password)
        server.send_message(msg)


def main():
    news_items = fetch_news()

    if not news_items:
        digest_text = "No news items fetched. Check RSS feeds or code."
    else:
        headlines_text = build_headlines_text(news_items)
        digest_text = ask_ai_for_digest(headlines_text)

    subject = "Your Business News Digest (Cause → Effect → Why it matters)"
    send_email(subject, digest_text)


if __name__ == "__main__":
    main()
