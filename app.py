import datetime
import json
import os
import secrets

from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, redirect, render_template, request,
                   session, url_for, flash, jsonify)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db, User, UserConfig, ScanHistory
from crypto_utils import encrypt, decrypt

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///emailscanner.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()

SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _make_flow(state=None):
    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': os.environ['GOOGLE_CLIENT_ID'],
                'client_secret': os.environ['GOOGLE_CLIENT_SECRET'],
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [url_for('auth_callback', _external=True)],
            }
        },
        scopes=SCOPES,
        state=state,
    )
    flow.redirect_uri = url_for('auth_callback', _external=True)
    return flow


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    user = get_current_user()
    if user:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login')
def login():
    if get_current_user():
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/auth/google')
def auth_google():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=state,
    )
    return redirect(auth_url)


@app.route('/auth/callback')
def auth_callback():
    if request.args.get('state') != session.get('oauth_state'):
        flash('Invalid OAuth state. Please try signing in again.', 'danger')
        return redirect(url_for('login'))

    flow = _make_flow(state=session.get('oauth_state'))
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    # Get user info from Google
    user_info_service = build('oauth2', 'v2', credentials=credentials, cache_discovery=False)
    user_info = user_info_service.userinfo().get().execute()

    google_id = user_info['id']
    email = user_info['email']
    name = user_info.get('name', '')
    picture = user_info.get('picture', '')

    # Upsert user
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User(google_id=google_id, email=email)
        db.session.add(user)

    user.name = name
    user.picture = picture
    user.access_token = credentials.token
    user.refresh_token = credentials.refresh_token or user.refresh_token
    if credentials.expiry:
        user.token_expiry = credentials.expiry

    db.session.commit()

    session['user_id'] = user.id
    session.pop('oauth_state', None)

    # New users go straight to admin to configure
    if not user.config:
        flash('Welcome! Please configure your settings to get started.', 'info')
        return redirect(url_for('admin'))

    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    scans = ScanHistory.query.filter_by(user_id=user.id).order_by(
        ScanHistory.scanned_at.desc()
    ).limit(20).all()
    config_complete = user.config and user.config.is_complete()
    return render_template('dashboard.html', user=user, scans=scans, config_complete=config_complete)


@app.route('/scan/<int:scan_id>')
@login_required
def view_scan(scan_id):
    user = get_current_user()
    scan = ScanHistory.query.filter_by(id=scan_id, user_id=user.id).first_or_404()
    return render_template('scan_detail.html', scan=scan, user=user)


# ---------------------------------------------------------------------------
# Routes — Admin
# ---------------------------------------------------------------------------

@app.route('/admin')
@login_required
def admin():
    user = get_current_user()
    config = user.config or UserConfig(user_id=user.id)

    # Decrypt sensitive fields for display (masked)
    smtp_password_set = bool(config._smtp_password)
    anthropic_key_set = bool(config._anthropic_key)

    return render_template(
        'admin.html',
        user=user,
        config=config,
        smtp_password_set=smtp_password_set,
        anthropic_key_set=anthropic_key_set,
    )


@app.route('/admin/save', methods=['POST'])
@login_required
def admin_save():
    user = get_current_user()

    config = user.config
    if not config:
        config = UserConfig(user_id=user.id)
        db.session.add(config)

    # Sender filters
    raw_emails = request.form.get('sender_emails', '').strip()
    raw_domains = request.form.get('sender_domains', '').strip()
    config.sender_emails = [e.strip() for e in raw_emails.splitlines() if e.strip()]
    config.sender_domains = [d.strip().lstrip('@') for d in raw_domains.splitlines() if d.strip()]

    # Delivery
    config.dest_email = request.form.get('dest_email', '').strip()
    config.smtp_host = request.form.get('smtp_host', 'smtp.gmail.com').strip()
    config.smtp_port = int(request.form.get('smtp_port', 587))
    config.smtp_user = request.form.get('smtp_user', '').strip()

    smtp_password = request.form.get('smtp_password', '').strip()
    if smtp_password:
        config._smtp_password = encrypt(smtp_password)

    # AI
    anthropic_key = request.form.get('anthropic_key', '').strip()
    if anthropic_key:
        config._anthropic_key = encrypt(anthropic_key)

    # Trusted domains
    raw_trusted = request.form.get('trusted_domains', '').strip()
    config.trusted_domains = [d.strip().lstrip('@') for d in raw_trusted.splitlines() if d.strip()]

    # Scan settings
    config.lookback_days = int(request.form.get('lookback_days', 7))

    db.session.commit()
    flash('Settings saved successfully.', 'success')
    return redirect(url_for('admin'))


# ---------------------------------------------------------------------------
# Routes — Manual scan trigger
# ---------------------------------------------------------------------------

@app.route('/scan/run', methods=['POST'])
@login_required
def run_scan_now():
    user = get_current_user()
    if not user.config or not user.config.is_complete():
        flash('Please complete your configuration before running a scan.', 'warning')
        return redirect(url_for('admin'))

    scan = _run_scan_for_user(user)
    db.session.add(scan)
    db.session.commit()

    if scan.status == 'success':
        flash(f'Scan complete! Found {scan.emails_found} emails. Digest sent to {user.config.dest_email}.', 'success')
    elif scan.status == 'no_emails':
        flash('Scan complete — no school emails found in the selected time window.', 'info')
    else:
        flash(f'Scan encountered an error: {scan.error_message}', 'danger')

    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Routes — GitHub Actions webhook
# ---------------------------------------------------------------------------

@app.route('/api/trigger-scan', methods=['POST'])
def api_trigger_scan():
    """Called by GitHub Actions every Saturday."""
    auth = request.headers.get('Authorization', '')
    expected = f'Bearer {os.environ.get("SCAN_SECRET", "")}'
    if not secrets.compare_digest(auth, expected):
        return jsonify({'error': 'Unauthorized'}), 401

    users = User.query.all()
    results = []

    for user in users:
        if not user.config or not user.config.is_complete():
            results.append({'user': user.email, 'status': 'skipped', 'reason': 'incomplete config'})
            continue

        scan = _run_scan_for_user(user)
        db.session.add(scan)
        db.session.commit()
        results.append({'user': user.email, 'status': scan.status, 'emails_found': scan.emails_found})

    return jsonify({'results': results})


# ---------------------------------------------------------------------------
# Core scan logic
# ---------------------------------------------------------------------------

def _run_scan_for_user(user):
    from gmail_client import build_gmail_service, fetch_school_emails
    from content_extractor import enrich_emails
    from summarizer import summarize_emails
    from email_sender import send_digest

    config = user.config
    scan = ScanHistory(user_id=user.id, status='pending')

    try:
        gmail_service = build_gmail_service(user)
        db.session.add(user)  # persist refreshed token

        emails = fetch_school_emails(
            gmail_service,
            config.sender_emails,
            config.sender_domains,
            config.lookback_days,
        )

        if not emails:
            scan.status = 'no_emails'
            scan.emails_found = 0
            return scan

        enriched = enrich_emails(emails, config.trusted_domains, gmail_service)

        urls_fetched = sum(len(e['url_contents']) for e in enriched)
        pdfs_parsed = sum(len(e['pdf_contents']) for e in enriched)

        anthropic_key = decrypt(config._anthropic_key)
        summary = summarize_emails(enriched, anthropic_key)

        smtp_password = decrypt(config._smtp_password)
        send_digest(
            summary_text=summary,
            dest_email=config.dest_email,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_user=config.smtp_user,
            smtp_password=smtp_password,
            school_email=user.email,
        )

        scan.status = 'success'
        scan.emails_found = len(emails)
        scan.urls_fetched = urls_fetched
        scan.pdfs_parsed = pdfs_parsed
        scan.summary = summary

    except Exception as e:
        scan.status = 'error'
        scan.error_message = str(e)
        print(f'Scan error for {user.email}: {e}')

    return scan


if __name__ == '__main__':
    app.run(debug=True, port=5000)
