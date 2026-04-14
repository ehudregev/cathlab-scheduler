from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash, abort
from app import db
from app.models import Doctor, Request, ScheduleEntry, ScheduleStatus, HistoryEntry
from app.scheduler import generate_schedule, get_israeli_holidays, get_month_days, is_session_day
from app.pdf_generator import generate_pdf
import uuid
import csv
import io
from datetime import date, datetime
import calendar

admin_bp = Blueprint("admin", __name__)

MONTH_NAMES = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
]


def current_month_year():
    today = date.today()
    return today.month, today.year


def submission_target_month():
    """Returns the month doctors are currently submitting for."""
    today = date.today()
    if today.day <= 15:
        if today.month == 12:
            return 1, today.year + 1
        return today.month + 1, today.year
    else:
        if today.month >= 11:
            return (today.month + 2) % 12 or 12, today.year + 1
        return today.month + 2, today.year


@admin_bp.route("/")
def dashboard():
    month, year = submission_target_month()
    doctors = Doctor.query.order_by(Doctor.name).all()
    requests = Request.query.filter_by(month=month, year=year).all()
    submitted_ids = {r.doctor_id for r in requests}
    status = ScheduleStatus.query.filter_by(month=month, year=year).first()
    return render_template(
        "admin/dashboard.html",
        doctors=doctors,
        submitted_ids=submitted_ids,
        month=month,
        year=year,
        month_name=MONTH_NAMES[month],
        status=status,
    )


@admin_bp.route("/doctors")
def doctors():
    doctors = Doctor.query.order_by(Doctor.name).all()
    return render_template("admin/doctors.html", doctors=doctors)


@admin_bp.route("/doctors/add", methods=["POST"])
def add_doctor():
    name = request.form.get("name", "").strip()
    does_oncall = "does_oncall" in request.form
    does_sessions = "does_sessions" in request.form
    if not name:
        return redirect(url_for("admin.doctors"))
    doctor = Doctor(
        name=name,
        does_oncall=does_oncall,
        does_sessions=does_sessions,
        token=str(uuid.uuid4()),
    )
    db.session.add(doctor)
    db.session.commit()
    return redirect(url_for("admin.doctors"))


@admin_bp.route("/doctors/<int:doctor_id>/delete", methods=["POST"])
def delete_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    db.session.delete(doctor)
    db.session.commit()
    return redirect(url_for("admin.doctors"))


def calc_fairness(doctors, entries, year, month, holiday_set):
    """
    Returns dict: {doctor_id: {
        month_weekday_oncalls, month_weekend_oncalls, month_sessions,
        annual_weekday_oncalls, annual_weekend_oncalls, annual_sessions
    }}
    Weekend on-calls = any day without sessions:
      Fri, Sat, holiday, holiday eve — each counted separately as 1.
    Weekday on-calls = regular Sun–Thu (not holiday/eve).
    """
    stats = {d.id: {
        "month_weekday_oncalls": 0,
        "month_weekend_oncalls": 0,
        "month_sessions": 0,
        "annual_weekday_oncalls": 0,
        "annual_weekend_oncalls": 0,
        "annual_sessions": 0,
    } for d in doctors}

    from datetime import date as dt
    for e in entries:
        if e.doctor_id not in stats:
            continue
        d = dt.fromisoformat(e.date_str)
        if e.entry_type == "oncall":
            # Special day = Fri, Sat, holiday, or holiday eve
            is_special = d.weekday() in (4, 5) or e.date_str in holiday_set
            if is_special:
                stats[e.doctor_id]["month_weekend_oncalls"] += 1
            else:
                stats[e.doctor_id]["month_weekday_oncalls"] += 1
        elif e.entry_type in ("session1", "session2"):
            stats[e.doctor_id]["month_sessions"] += 1

    # Annual cumulative from HistoryEntry (all months this year except current)
    history = HistoryEntry.query.filter(
        HistoryEntry.year == year,
        HistoryEntry.month != month,
    ).all()
    for h in history:
        if h.doctor_id not in stats:
            continue
        stats[h.doctor_id]["annual_weekday_oncalls"] += h.weekday_oncalls
        stats[h.doctor_id]["annual_weekend_oncalls"] += h.weekend_oncalls
        stats[h.doctor_id]["annual_sessions"] += h.sessions

    # Add current month to annual totals
    for doc_id, s in stats.items():
        s["annual_weekday_oncalls"] += s["month_weekday_oncalls"]
        s["annual_weekend_oncalls"] += s["month_weekend_oncalls"]
        s["annual_sessions"] += s["month_sessions"]

    return stats


@admin_bp.route("/schedule/<int:year>/<int:month>")
def view_schedule(year, month):
    days = get_month_days(year, month)
    holiday_set = get_israeli_holidays(year)
    entries = ScheduleEntry.query.filter_by(month=month, year=year).all()
    entry_map = {(e.date_str, e.entry_type): e for e in entries}
    doctors = Doctor.query.order_by(Doctor.name).all()
    status = ScheduleStatus.query.filter_by(month=month, year=year).first()
    fairness = calc_fairness(doctors, entries, year, month, holiday_set)

    return render_template(
        "admin/schedule.html",
        days=days,
        holiday_set=holiday_set,
        entry_map=entry_map,
        doctors=doctors,
        month=month,
        year=year,
        month_name=MONTH_NAMES[month],
        status=status,
        is_session_day=is_session_day,
        fairness=fairness,
    )


@admin_bp.route("/schedule/<int:year>/<int:month>/generate", methods=["POST"])
def generate(year, month):
    # Clear existing draft entries
    ScheduleEntry.query.filter_by(month=month, year=year).delete()
    db.session.commit()

    result = generate_schedule(year, month, db, Doctor, Request, ScheduleEntry, HistoryEntry)

    for e in result["entries"]:
        entry = ScheduleEntry(
            month=month,
            year=year,
            date_str=e["date_str"],
            entry_type=e["entry_type"],
            doctor_id=e["doctor_id"],
            is_empty=(e["doctor_id"] is None),
        )
        db.session.add(entry)

    status = ScheduleStatus.query.filter_by(month=month, year=year).first()
    if not status:
        status = ScheduleStatus(month=month, year=year)
        db.session.add(status)
    status.status = "draft"
    status.alerts = result["alerts"]
    db.session.commit()

    return redirect(url_for("admin.view_schedule", year=year, month=month))


@admin_bp.route("/schedule/<int:year>/<int:month>/update", methods=["POST"])
def update_entry(year, month):
    date_str = request.form.get("date_str")
    entry_type = request.form.get("entry_type")
    doctor_id = request.form.get("doctor_id") or None
    if doctor_id:
        doctor_id = int(doctor_id)

    entry = ScheduleEntry.query.filter_by(
        month=month, year=year, date_str=date_str, entry_type=entry_type
    ).first()

    if entry:
        entry.doctor_id = doctor_id
        entry.is_empty = (doctor_id is None)
    else:
        entry = ScheduleEntry(
            month=month, year=year,
            date_str=date_str, entry_type=entry_type,
            doctor_id=doctor_id, is_empty=(doctor_id is None)
        )
        db.session.add(entry)

    db.session.commit()
    return redirect(url_for("admin.view_schedule", year=year, month=month))


@admin_bp.route("/schedule/<int:year>/<int:month>/publish", methods=["POST"])
def publish(year, month):
    from app.scheduler import save_schedule_to_history
    status = ScheduleStatus.query.filter_by(month=month, year=year).first()
    if status:
        status.status = "published"
        status.published_at = datetime.utcnow()
        db.session.commit()
    # Save this month's counts to history so next month's algorithm is fair
    save_schedule_to_history(year, month, db, ScheduleEntry, HistoryEntry, Doctor)
    return redirect(url_for("admin.view_schedule", year=year, month=month))


@admin_bp.route("/requests/<int:year>/<int:month>")
def view_requests(year, month):
    doctors = Doctor.query.order_by(Doctor.name).all()
    requests = Request.query.filter_by(month=month, year=year).all()
    req_by_doctor = {r.doctor_id: r for r in requests}
    import calendar
    num_days = calendar.monthrange(year, month)[1]
    days = list(range(1, num_days + 1))
    return render_template(
        "admin/requests.html",
        doctors=doctors,
        req_by_doctor=req_by_doctor,
        month=month,
        year=year,
        month_name=MONTH_NAMES[month],
        days=days,
    )


@admin_bp.route("/schedule/<int:year>/<int:month>/pdf")
def download_pdf(year, month):
    days = get_month_days(year, month)
    holiday_set = get_israeli_holidays(year)
    entries = ScheduleEntry.query.filter_by(month=month, year=year).all()
    entry_map = {(e.date_str, e.entry_type): e for e in entries}
    doctors = {d.id: d for d in Doctor.query.all()}

    pdf_bytes = generate_pdf(year, month, MONTH_NAMES[month], days, holiday_set, entry_map, doctors)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"לוח_{MONTH_NAMES[month]}_{year}.pdf",
    )


# ── HISTORY IMPORT ──────────────────────────────────────────────────────────

@admin_bp.route("/history")
def history():
    doctors = Doctor.query.order_by(Doctor.name).all()
    history = HistoryEntry.query.order_by(HistoryEntry.year.desc(), HistoryEntry.month.desc()).all()
    return render_template("admin/history.html", doctors=doctors, history=history)


@admin_bp.route("/history/add", methods=["POST"])
def add_history():
    doctor_id = request.form.get("doctor_id", type=int)
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int)
    weekday_oncalls = request.form.get("weekday_oncalls", 0, type=int)
    weekend_oncalls = request.form.get("weekend_oncalls", 0, type=int)
    sessions = request.form.get("sessions", 0, type=int)

    existing = HistoryEntry.query.filter_by(
        doctor_id=doctor_id, month=month, year=year
    ).first()
    if existing:
        existing.weekday_oncalls = weekday_oncalls
        existing.weekend_oncalls = weekend_oncalls
        existing.sessions = sessions
    else:
        entry = HistoryEntry(
            doctor_id=doctor_id, month=month, year=year,
            weekday_oncalls=weekday_oncalls,
            weekend_oncalls=weekend_oncalls,
            sessions=sessions,
        )
        db.session.add(entry)
    db.session.commit()
    return redirect(url_for("admin.history"))


@admin_bp.route("/history/delete/<int:entry_id>", methods=["POST"])
def delete_history(entry_id):
    entry = HistoryEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for("admin.history"))


@admin_bp.route("/history/import-csv", methods=["POST"])
def import_history_csv():
    """
    CSV format: doctor_name, month, year, weekday_oncalls, weekend_oncalls, sessions
    Header row is skipped.
    """
    file = request.files.get("csv_file")
    if not file:
        return redirect(url_for("admin.history"))

    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)

    errors = []
    imported = 0
    for row in reader:
        try:
            name = row.get("doctor_name", "").strip()
            month = int(row.get("month", 0))
            year = int(row.get("year", 0))
            weekday_oncalls = int(row.get("weekday_oncalls", 0))
            weekend_oncalls = int(row.get("weekend_oncalls", 0))
            sessions = int(row.get("sessions", 0))

            doctor = Doctor.query.filter(Doctor.name.ilike(name)).first()
            if not doctor:
                errors.append(f"רופא לא נמצא: {name}")
                continue

            existing = HistoryEntry.query.filter_by(
                doctor_id=doctor.id, month=month, year=year
            ).first()
            if existing:
                existing.weekday_oncalls += weekday_oncalls
                existing.weekend_oncalls += weekend_oncalls
                existing.sessions += sessions
            else:
                entry = HistoryEntry(
                    doctor_id=doctor.id, month=month, year=year,
                    weekday_oncalls=weekday_oncalls,
                    weekend_oncalls=weekend_oncalls,
                    sessions=sessions,
                )
                db.session.add(entry)
            imported += 1
        except Exception as ex:
            errors.append(str(ex))

    db.session.commit()
    return render_template("admin/history.html",
                           doctors=Doctor.query.order_by(Doctor.name).all(),
                           history=HistoryEntry.query.order_by(
                               HistoryEntry.year.desc(), HistoryEntry.month.desc()).all(),
                           import_errors=errors,
                           import_count=imported)
