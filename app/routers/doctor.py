from flask import Blueprint, render_template, request, redirect, url_for
from app import db
from app.models import Doctor, Request
from datetime import datetime, date
import calendar

doctor_bp = Blueprint("doctor", __name__)


def get_target_month():
    today = date.today()
    if today.day <= 15:
        if today.month == 12:
            return 1, today.year + 1
        return today.month + 1, today.year
    else:
        if today.month >= 11:
            return (today.month + 2) % 12 or 12, today.year + (1 if today.month >= 11 else 0)
        return today.month + 2, today.year


@doctor_bp.route("/<token>")
def request_form(token):
    doctor = Doctor.query.filter_by(token=token).first_or_404()
    month, year = get_target_month()

    existing = Request.query.filter_by(
        doctor_id=doctor.id, month=month, year=year
    ).first()

    num_days = calendar.monthrange(year, month)[1]
    month_name = [
        "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
        "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
    ][month]

    # Build existing state map {date_str: state}
    existing_states = {}
    if existing:
        for d in existing.want_session:
            existing_states[d] = "want_session"
        for d in existing.want_oncall:
            existing_states[d] = "want_oncall"
        for d in existing.no_session:
            existing_states[d] = "no_session"
        for d in existing.no_oncall:
            existing_states[d] = "no_oncall"
        for d in existing.no_both:
            existing_states[d] = "no_both"

    import json
    return render_template(
        "doctor/request.html",
        doctor=doctor,
        month=month,
        year=year,
        month_name=month_name,
        num_days=num_days,
        existing=existing,
        existing_states_json=json.dumps(existing_states),
    )


@doctor_bp.route("/<token>/submit", methods=["POST"])
def submit_request(token):
    doctor = Doctor.query.filter_by(token=token).first_or_404()
    month, year = get_target_month()

    want_session = request.form.getlist("want_session[]")
    want_oncall = request.form.getlist("want_oncall[]")
    no_session = request.form.getlist("no_session[]")
    no_oncall = request.form.getlist("no_oncall[]")
    no_both = request.form.getlist("no_both[]")
    desired_sessions = request.form.get("desired_sessions", type=int)

    existing = Request.query.filter_by(
        doctor_id=doctor.id, month=month, year=year
    ).first()

    if existing:
        existing.want_session = want_session
        existing.want_oncall = want_oncall
        existing.no_session = no_session
        existing.no_oncall = no_oncall
        existing.no_both = no_both
        if doctor.does_sessions:
            existing.desired_sessions = desired_sessions
        existing.submitted_at = datetime.utcnow()
    else:
        req = Request(
            doctor_id=doctor.id,
            month=month,
            year=year,
            desired_sessions=desired_sessions if doctor.does_sessions else None,
        )
        req.want_session = want_session
        req.want_oncall = want_oncall
        req.no_session = no_session
        req.no_oncall = no_oncall
        req.no_both = no_both
        db.session.add(req)

    db.session.commit()
    return render_template("doctor/submitted.html", doctor=doctor, month_name=[
        "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
        "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
    ][month], year=year)
