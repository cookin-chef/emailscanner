import io
import re
from urllib.parse import urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 10
USER_AGENT = 'Mozilla/5.0 (compatible; SchoolEmailDigest/1.0)'


def is_trusted_url(url, trusted_domains):
    """Return True if the URL's domain matches any trusted domain."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        for domain in trusted_domains:
            domain = domain.lstrip('@').lower()
            if hostname == domain or hostname.endswith('.' + domain):
                return True
    except Exception:
        pass
    return False


def fetch_url_text(url):
    """Fetch a URL and return cleaned text content."""
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        if 'pdf' in content_type:
            return extract_pdf_text(response.content)

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove nav, footer, scripts, styles
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()

        text = soup.get_text(separator='\n', strip=True)
        # Collapse excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text[:5000]  # cap to avoid overwhelming Claude
    except Exception as e:
        return f'[Could not fetch URL: {e}]'


def extract_pdf_text(pdf_bytes):
    """Extract text from PDF bytes."""
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        text = '\n'.join(text_parts)
        return text[:5000]  # cap per PDF
    except Exception as e:
        return f'[Could not extract PDF text: {e}]'


def enrich_emails(emails, trusted_domains, gmail_service):
    """
    For each email, fetch trusted URLs and extract PDF attachments.
    Returns a list of enriched email dicts with added 'url_contents' and 'pdf_contents'.
    """
    from gmail_client import fetch_attachment

    enriched = []
    for email in emails:
        url_contents = []
        pdf_contents = []

        # Fetch trusted URLs
        for url in email.get('urls', []):
            if is_trusted_url(url, trusted_domains):
                text = fetch_url_text(url)
                url_contents.append({'url': url, 'text': text})

        # Extract PDF attachments
        for att in email.get('attachments', []):
            if att['type'] == 'pdf':
                raw = fetch_attachment(gmail_service, att['message_id'], att['id'])
                if raw:
                    text = extract_pdf_text(raw)
                    pdf_contents.append({'filename': att['filename'], 'text': text})

        enriched.append({
            **email,
            'url_contents': url_contents,
            'pdf_contents': pdf_contents,
        })

    return enriched
