from flask import Blueprint, render_template, request, redirect, url_for, abort
from app import db
from app.models import Doctor, Request
from datetime import datetime, date
import calendar

doctor_bp = Blueprint("doctor", __name__)


def get_target_month():
    """Doctors submit for next month. If past the 15th, show month after next."""
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

    return render_template(
        "doctor/request.html",
        doctor=doctor,
        month=month,
        year=year,
        month_name=month_name,
        num_days=num_days,
        existing=existing,
    )


@doctor_bp.route("/<token>/submit", methods=["POST"])
def submit_request(token):
    doctor = Doctor.query.filter_by(token=token).first_or_404()
    month, year = get_target_month()

    preferred = request.form.getlist("preferred[]")
    unavailable = request.form.getlist("unavailable[]")
    desired_sessions = request.form.get("desired_sessions", type=int)

    existing = Request.query.filter_by(
        doctor_id=doctor.id, month=month, year=year
    ).first()

    if existing:
        existing.preferred_dates = preferred
        existing.unavailable_dates = unavailable
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
        req.preferred_dates = preferred
        req.unavailable_dates = unavailable
        db.session.add(req)

    db.session.commit()
    return render_template("doctor/submitted.html", doctor=doctor, month_name=[
        "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
        "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
    ][month], year=year)
