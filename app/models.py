from app import db
from datetime import datetime
import json


class Doctor(db.Model):
    __tablename__ = "doctors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    does_oncall = db.Column(db.Boolean, default=False)
    does_sessions = db.Column(db.Boolean, default=False)
    token = db.Column(db.String(36), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requests = db.relationship("Request", backref="doctor", lazy=True)
    history = db.relationship("HistoryEntry", backref="doctor", lazy=True)


class Request(db.Model):
    __tablename__ = "requests"
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    desired_sessions = db.Column(db.Integer, nullable=True)
    preferred_dates_json = db.Column(db.Text, default="[]")
    unavailable_dates_json = db.Column(db.Text, default="[]")
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("doctor_id", "month", "year", name="uq_doctor_month_year"),
    )

    @property
    def preferred_dates(self):
        return json.loads(self.preferred_dates_json or "[]")

    @preferred_dates.setter
    def preferred_dates(self, value):
        self.preferred_dates_json = json.dumps(value)

    @property
    def unavailable_dates(self):
        return json.loads(self.unavailable_dates_json or "[]")

    @unavailable_dates.setter
    def unavailable_dates(self, value):
        self.unavailable_dates_json = json.dumps(value)


class ScheduleEntry(db.Model):
    __tablename__ = "schedule_entries"
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    date_str = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    entry_type = db.Column(db.String(20), nullable=False)  # oncall / session1 / session2
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True)
    is_empty = db.Column(db.Boolean, default=False)

    doctor = db.relationship("Doctor")

    __table_args__ = (
        db.UniqueConstraint("month", "year", "date_str", "entry_type", name="uq_entry"),
    )


class ScheduleStatus(db.Model):
    __tablename__ = "schedule_status"
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="draft")  # draft / published
    published_at = db.Column(db.DateTime, nullable=True)
    alerts_json = db.Column(db.Text, default="[]")

    __table_args__ = (
        db.UniqueConstraint("month", "year", name="uq_schedule_month_year"),
    )

    @property
    def alerts(self):
        return json.loads(self.alerts_json or "[]")

    @alerts.setter
    def alerts(self, value):
        self.alerts_json = json.dumps(value)


class HistoryEntry(db.Model):
    """Stores historical on-call/session counts per doctor per month."""
    __tablename__ = "history_entries"
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    weekday_oncalls = db.Column(db.Integer, default=0)
    weekend_oncalls = db.Column(db.Integer, default=0)
    sessions = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint("doctor_id", "month", "year", name="uq_history"),
    )
