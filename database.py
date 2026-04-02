from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

class Video(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=True)  # nullable for old videos
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.BigInteger, default=0)
    duration = db.Column(db.Float, default=0)
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    codec = db.Column(db.String(50), default='')
    status = db.Column(db.String(20), default='queued')  # queued, processing, ready, error
    views = db.Column(db.Integer, default=0)
    thumbnail_path = db.Column(db.String(512), nullable=True)
    hls_path = db.Column(db.String(512), nullable=True)
    s3_url = db.Column(db.String(1024), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'file_size': self.file_size,
            'duration': self.duration,
            'width': self.width,
            'height': self.height,
            'codec': self.codec,
            'status': self.status,
            'views': self.views,
            'has_thumbnail': bool(self.thumbnail_path),
            'has_hls': bool(self.hls_path),
            's3_url': self.s3_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }

def init_db(app):
    with app.app_context():
        db.create_all()
