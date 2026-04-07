from models_v2 import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import ForeignKey


class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(100))
    role          = db.Column(db.String(20), default='staff')   # admin | staff
    is_active     = db.Column(db.Boolean, default=True)
    can_delete    = db.Column(db.Boolean, default=False)  # allowed to delete records
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)

    # ── password helpers ─────────────────────────────────────────────────────
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ── convenience ──────────────────────────────────────────────────────────
    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


class DeleteRequest(db.Model):
    __tablename__ = 'delete_requests'

    id           = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, ForeignKey('users.id'), nullable=True)
    entity_type  = db.Column(db.String(30))   # wave | trip | breakdown | master
    entity_id    = db.Column(db.Integer)
    entity_info  = db.Column(db.String(300))  # human-readable description
    reason       = db.Column(db.Text)
    status       = db.Column(db.String(20), default='pending')  # pending | approved | rejected
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by  = db.Column(db.String(80))
    reviewed_at  = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)

    requester = db.relationship('User', foreign_keys=[requester_id])
