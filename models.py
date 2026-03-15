import json
import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    name = db.Column(db.String(200))
    picture = db.Column(db.String(500))
    access_token = db.Column(db.Text)
    refresh_token = db.Column(db.Text)
    token_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    config = db.relationship('UserConfig', back_populates='user', uselist=False, cascade='all, delete-orphan')
    scans = db.relationship('ScanHistory', back_populates='user', cascade='all, delete-orphan', order_by='ScanHistory.scanned_at.desc()')

    def is_token_expired(self):
        if not self.token_expiry:
            return True
        return datetime.datetime.utcnow() >= self.token_expiry


class UserConfig(db.Model):
    __tablename__ = 'user_configs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)

    # Email filter settings
    _sender_emails = db.Column('sender_emails', db.Text, default='[]')
    _sender_domains = db.Column('sender_domains', db.Text, default='[]')

    # Delivery settings
    dest_email = db.Column(db.String(200))
    smtp_host = db.Column(db.String(200), default='smtp.gmail.com')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(200))
    _smtp_password = db.Column('smtp_password', db.Text)

    # AI settings
    _anthropic_key = db.Column('anthropic_key', db.Text)

    # URL fetching settings
    _trusted_domains = db.Column('trusted_domains', db.Text, default='["smore.com"]')

    # Scan settings
    lookback_days = db.Column(db.Integer, default=7)

    user = db.relationship('User', back_populates='config')

    @property
    def sender_emails(self):
        return json.loads(self._sender_emails or '[]')

    @sender_emails.setter
    def sender_emails(self, value):
        self._sender_emails = json.dumps(value)

    @property
    def sender_domains(self):
        return json.loads(self._sender_domains or '[]')

    @sender_domains.setter
    def sender_domains(self, value):
        self._sender_domains = json.dumps(value)

    @property
    def trusted_domains(self):
        return json.loads(self._trusted_domains or '["smore.com"]')

    @trusted_domains.setter
    def trusted_domains(self, value):
        self._trusted_domains = json.dumps(value)

    def is_complete(self):
        """Returns True if the config has enough info to run a scan."""
        has_filters = bool(self.sender_emails or self.sender_domains)
        has_dest = bool(self.dest_email)
        has_smtp = bool(self.smtp_host and self.smtp_user and self._smtp_password)
        has_ai = bool(self._anthropic_key)
        return has_filters and has_dest and has_smtp and has_ai


class ScanHistory(db.Model):
    __tablename__ = 'scan_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    emails_found = db.Column(db.Integer, default=0)
    urls_fetched = db.Column(db.Integer, default=0)
    pdfs_parsed = db.Column(db.Integer, default=0)
    summary = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')  # pending, success, no_emails, error
    error_message = db.Column(db.Text)

    user = db.relationship('User', back_populates='scans')
