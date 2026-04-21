from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    database_url = os.environ.get("DATABASE_URL", "sqlite:///cathlab.db")
    # Railway uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

    db.init_app(app)

    from app.routers.admin import admin_bp
    from app.routers.doctor import doctor_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(doctor_bp, url_prefix="/doctor")

    with app.app_context():
        db.create_all()
        _migrate(db)

    return app


def _migrate(db):
    """Add missing columns to existing tables without Alembic."""
    new_columns = [
        ("requests", "want_session_json", "TEXT DEFAULT '[]'"),
        ("requests", "want_oncall_json",  "TEXT DEFAULT '[]'"),
        ("requests", "want_both_json",    "TEXT DEFAULT '[]'"),
        ("requests", "no_session_json",   "TEXT DEFAULT '[]'"),
        ("requests", "no_oncall_json",    "TEXT DEFAULT '[]'"),
        ("requests", "no_both_json",      "TEXT DEFAULT '[]'"),
        ("history_entries", "session1_count", "INTEGER DEFAULT 0"),
        ("history_entries", "weekend_units", "INTEGER DEFAULT 0"),
    ]
    with db.engine.connect() as conn:
        for table, column, col_def in new_columns:
            try:
                conn.execute(
                    db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                )
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — skip
