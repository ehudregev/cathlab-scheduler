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
    # Per-date preferences (JSON lists of date strings YYYY-MM-DD)
    want_session_json = db.Column(db.Text, default="[]")       # רוצה ססיה
    want_oncall_json = db.Column(db.Text, default="[]")        # רוצה כוננות
    want_both_json = db.Column(db.Text, default="[]")          # רוצה גם ססיה וגם כוננות
    no_session_json = db.Column(db.Text, default="[]")         # לא יכול ססיה
    no_oncall_json = db.Column(db.Text, default="[]")          # לא יכול כוננות
    no_both_json = db.Column(db.Text, default="[]")            # לא יכול כלום
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("doctor_id", "month", "year", name="uq_doctor_month_year"),
    )

    def _get(self, field):
        return json.loads(getattr(self, field) or "[]")

    def _set(self, field, value):
        setattr(self, field, json.dumps(value))

    @property
    def want_session(self): return self._get("want_session_json")
    @want_session.setter
    def want_session(self, v): self._set("want_session_json", v)

    @property
    def want_oncall(self): return self._get("want_oncall_json")
    @want_oncall.setter
    def want_oncall(self, v): self._set("want_oncall_json", v)

    @property
    def want_both(self): return self._get("want_both_json")
    @want_both.setter
    def want_both(self, v): self._set("want_both_json", v)

    @property
    def no_session(self): return self._get("no_session_json")
    @no_session.setter
    def no_session(self, v): self._set("no_session_json", v)

    @property
    def no_oncall(self): return self._get("no_oncall_json")
    @no_oncall.setter
    def no_oncall(self, v): self._set("no_oncall_json", v)

    @property
    def no_both(self): return self._get("no_both_json")
    @no_both.setter
    def no_both(self, v): self._set("no_both_json", v)

    # Derived helpers for the scheduler
    @property
    def unavailable_oncall(self):
        """Dates where doctor can't do on-call."""
        return set(self.no_oncall) | set(self.no_both)

    @property
    def unavailable_session(self):
        """Dates where doctor can't do session."""
        return set(self.no_session) | set(self.no_both)

    @property
    def preferred_oncall(self):
        return set(self.want_oncall) | set(self.want_both)

    @property
    def preferred_session(self):
        return set(self.want_session) | set(self.want_both)


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
    session1_count = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint("doctor_id", "month", "year", name="uq_history"),
    )
