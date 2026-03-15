import base64
import datetime
import json
import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
]


def build_gmail_service(user):
    """Build an authenticated Gmail service from a User model instance."""
    creds = Credentials(
        token=user.access_token,
        refresh_token=user.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
        scopes=SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist refreshed token back to user
        user.access_token = creds.token
        if creds.expiry:
            user.token_expiry = creds.expiry

    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def build_search_query(sender_emails, sender_domains, lookback_days):
    """Build a Gmail search query string."""
    parts = []
    for email in sender_emails:
        parts.append(f'from:{email}')
    for domain in sender_domains:
        domain = domain.lstrip('@')
        parts.append(f'from:@{domain}')

    if not parts:
        return None

    sender_query = ' OR '.join(parts)
    return f'({sender_query}) newer_than:{lookback_days}d'


def fetch_school_emails(gmail_service, sender_emails, sender_domains, lookback_days=7):
    """Fetch and parse school emails from Gmail."""
    query = build_search_query(sender_emails, sender_domains, lookback_days)
    if not query:
        return []

    results = gmail_service.users().messages().list(
        userId='me', q=query, maxResults=50
    ).execute()

    message_refs = results.get('messages', [])
    if not message_refs:
        return []

    emails = []
    for ref in message_refs:
        try:
            full_msg = gmail_service.users().messages().get(
                userId='me', id=ref['id'], format='full'
            ).execute()
            parsed = _parse_message(full_msg)
            emails.append(parsed)
        except Exception as e:
            print(f"Error fetching message {ref['id']}: {e}")
            continue

    return emails


def fetch_attachment(gmail_service, message_id, attachment_id):
    """Fetch raw attachment data from Gmail."""
    result = gmail_service.users().messages().attachments().get(
        userId='me', messageId=message_id, id=attachment_id
    ).execute()
    data = result.get('data', '')
    return base64.urlsafe_b64decode(data) if data else None


def _decode_body(data):
    """Decode base64url encoded body data."""
    if not data:
        return ''
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')


def _parse_message(msg):
    """Parse a Gmail message into a structured dict."""
    payload = msg.get('payload', {})
    headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}

    subject = headers.get('subject', 'No Subject')
    sender = headers.get('from', '')
    date = headers.get('date', '')
    message_id = msg.get('id', '')

    body_text = ''
    body_html = ''
    attachments = []
    urls = []

    def process_parts(parts):
        nonlocal body_text, body_html
        for part in parts:
            mime = part.get('mimeType', '')
            body_data = part.get('body', {})

            if mime == 'text/plain':
                body_text += _decode_body(body_data.get('data', ''))
            elif mime == 'text/html':
                body_html += _decode_body(body_data.get('data', ''))
            elif mime == 'application/pdf':
                att_id = body_data.get('attachmentId')
                filename = part.get('filename', 'attachment.pdf')
                if att_id:
                    attachments.append({
                        'id': att_id,
                        'message_id': message_id,
                        'filename': filename,
                        'type': 'pdf',
                    })
            elif 'multipart' in mime:
                process_parts(part.get('parts', []))

    if 'parts' in payload:
        process_parts(payload['parts'])
    else:
        mime = payload.get('mimeType', '')
        data = payload.get('body', {}).get('data', '')
        content = _decode_body(data)
        if mime == 'text/html':
            body_html = content
        else:
            body_text = content

    # Extract URLs and clean text from HTML
    if body_html:
        soup = BeautifulSoup(body_html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http'):
                urls.append(href)
        if not body_text:
            body_text = soup.get_text(separator='\n', strip=True)

    return {
        'id': message_id,
        'subject': subject,
        'sender': sender,
        'date': date,
        'body': body_text.strip(),
        'urls': list(dict.fromkeys(urls)),  # deduplicate preserving order
        'attachments': attachments,
    }
