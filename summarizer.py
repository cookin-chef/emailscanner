import anthropic

SYSTEM_PROMPT = """You are a helpful assistant that reads school emails and summarizes them for a busy parent.
Your job is to extract the most important information and present it clearly and concisely.
Focus only on what's relevant to the upcoming school week.
Be factual — do not add information that isn't in the emails."""

SUMMARY_PROMPT = """I'm a parent and I received the following emails from my child's school over the past week.
Please read through all of them (including any newsletter content and PDF text) and give me a clear, organized summary.

Structure your summary with these sections (only include a section if there's relevant content):

📅 **UPCOMING EVENTS & DATES**
List any events, activities, or important dates mentioned.

📋 **ACTION ITEMS & DEADLINES**
Anything I need to do, sign, return, pay, or respond to — with deadlines.

🎒 **ACTIVITIES & FIELD TRIPS**
Extracurricular activities, field trips, sports, clubs.

📢 **IMPORTANT ANNOUNCEMENTS**
Policy changes, school news, safety notices, or anything else I should know.

🔗 **USEFUL LINKS**
Any important links mentioned (sign-up forms, event pages, etc.).

At the end, add a short **"This Week At A Glance"** — 3 to 5 bullet points of the most time-sensitive things I should act on before Monday.

---

Here are the emails:

{email_content}"""


def build_email_content(enriched_emails):
    """Format enriched emails into a single text block for Claude."""
    parts = []
    for i, email in enumerate(enriched_emails, 1):
        section = [
            f'--- EMAIL {i} ---',
            f'Subject: {email["subject"]}',
            f'From: {email["sender"]}',
            f'Date: {email["date"]}',
            '',
            'Body:',
            email['body'] or '(no body text)',
        ]

        for uc in email.get('url_contents', []):
            section += [
                '',
                f'Newsletter/Link content from {uc["url"]}:',
                uc['text'],
            ]

        for pc in email.get('pdf_contents', []):
            section += [
                '',
                f'PDF attachment "{pc["filename"]}":',
                pc['text'],
            ]

        parts.append('\n'.join(section))

    return '\n\n'.join(parts)


def summarize_emails(enriched_emails, anthropic_key):
    """Send enriched emails to Claude and return a formatted summary."""
    client = anthropic.Anthropic(api_key=anthropic_key)

    email_content = build_email_content(enriched_emails)
    prompt = SUMMARY_PROMPT.format(email_content=email_content)

    message = client.messages.create(
        model='claude-opus-4-6',
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': prompt}],
    )

    return message.content[0].text
