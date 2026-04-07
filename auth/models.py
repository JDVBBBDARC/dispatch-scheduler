from models_v2 import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


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
