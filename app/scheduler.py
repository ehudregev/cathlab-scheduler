"""
Scheduling algorithm for cathlab on-call and sessions.
"""
from datetime import date, timedelta
import calendar
import holidays as holidays_lib
from collections import defaultdict


def get_israeli_holidays(year):
    """Return a set of date strings (YYYY-MM-DD) that are Israeli holidays or holiday eves."""
    il_holidays = holidays_lib.Israel(years=year)
    result = set()
    for d in il_holidays.keys():
        result.add(d.strftime("%Y-%m-%d"))
        # Add eve (day before)
        eve = d - timedelta(days=1)
        result.add(eve.strftime("%Y-%m-%d"))
    return result


def get_month_days(year, month):
    """Return list of date objects for each day in the month."""
    num_days = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, num_days + 1)]


def is_weekend(d):
    """Friday=4, Saturday=5 in Python weekday()."""
    return d.weekday() in (4, 5)


def is_session_day(d, holiday_set):
    """Session days: Sunday-Thursday, not holiday or holiday eve."""
    date_str = d.strftime("%Y-%m-%d")
    # Sunday=6, Monday=0, Tuesday=1, Wednesday=2, Thursday=3
    is_weekday = d.weekday() in (0, 1, 2, 3, 6)
    return is_weekday and date_str not in holiday_set


def get_weekend_units(days):
    """Group Friday+Saturday pairs. Returns list of (friday, saturday) tuples."""
    units = []
    fridays = [d for d in days if d.weekday() == 4]
    for fri in fridays:
        sat = fri + timedelta(days=1)
        units.append((fri, sat))
    return units


def get_cumulative_counts(doctors, month, year, db, HistoryEntry, ScheduleEntry):
    """
    Get cumulative historical counts for each doctor up to (but not including) this month.
    Returns dict: {doctor_id: {"weekday_oncalls": int, "weekend_oncalls": int, "sessions": int}}
    """
    from sqlalchemy import or_

    counts = {}
    for doc in doctors:
        # Sum all history entries before this month/year
        entries = HistoryEntry.query.filter(
            HistoryEntry.doctor_id == doc.id,
            or_(
                HistoryEntry.year < year,
                (HistoryEntry.year == year) & (HistoryEntry.month < month)
            )
        ).all()
        counts[doc.id] = {
            "weekday_oncalls": sum(e.weekday_oncalls for e in entries),
            "weekend_oncalls": sum(e.weekend_oncalls for e in entries),
            "sessions": sum(e.sessions for e in entries),
        }
    return counts


def generate_schedule(year, month, db, Doctor, Request, ScheduleEntry, HistoryEntry):
    """
    Main scheduling function. Returns:
    {
        "entries": list of dicts {date_str, entry_type, doctor_id},
        "alerts": list of alert strings
    }
    """
    alerts = []
    entries = []

    holiday_set = get_israeli_holidays(year)
    days = get_month_days(year, month)

    # Load doctors
    oncall_doctors = Doctor.query.filter_by(does_oncall=True).all()
    session_doctors = Doctor.query.filter_by(does_sessions=True).all()

    # Load requests for this month
    requests = Request.query.filter_by(month=month, year=year).all()
    req_by_doctor = {r.doctor_id: r for r in requests}

    # Cumulative counts
    oncall_counts = get_cumulative_counts(oncall_doctors, month, year, db, HistoryEntry, ScheduleEntry)
    session_counts = get_cumulative_counts(session_doctors, month, year, db, HistoryEntry, ScheduleEntry)

    # Build per-type unavailability and preference sets
    unavailable_oncall = {}
    unavailable_session = {}
    preferred_oncall = {}
    preferred_session = {}

    for doc in oncall_doctors + session_doctors:
        r = req_by_doctor.get(doc.id)
        if r:
            unavailable_oncall[doc.id] = r.unavailable_oncall
            unavailable_session[doc.id] = r.unavailable_session
            preferred_oncall[doc.id] = r.preferred_oncall
            preferred_session[doc.id] = r.preferred_session
        else:
            unavailable_oncall[doc.id] = set()
            unavailable_session[doc.id] = set()
            preferred_oncall[doc.id] = set()
            preferred_session[doc.id] = set()

    # Backwards compat alias for on-call scheduling
    unavailable = unavailable_oncall
    preferred = preferred_oncall

    # ── ON-CALL SCHEDULING ──────────────────────────────────────────────────

    weekend_units = get_weekend_units(days)
    # All weekdays (including holidays) need on-call coverage
    weekday_oncall_days_all = [d for d in days if d.weekday() in (0, 1, 2, 3, 6)]

    # Weekend on-call assignment
    weekend_assigned = {}
    weekend_count = {d.id: oncall_counts[d.id]["weekend_oncalls"] for d in oncall_doctors}
    total_oncall_count = {
        d.id: oncall_counts[d.id]["weekday_oncalls"] + oncall_counts[d.id]["weekend_oncalls"]
        for d in oncall_doctors
    }

    for (fri, sat) in weekend_units:
        fri_str = fri.strftime("%Y-%m-%d")
        sat_str = sat.strftime("%Y-%m-%d")

        # Sort doctors by fewest weekend oncalls, then prefer those who prefer this date
        candidates = sorted(
            oncall_doctors,
            key=lambda d: (
                fri_str in unavailable[d.id] or sat_str in unavailable[d.id],  # unavailable last
                weekend_count[d.id],  # fewest oncalls first
                -(fri_str in preferred[d.id] or sat_str in preferred[d.id])  # prefer preferred
            )
        )

        assigned = None
        for doc in candidates:
            if fri_str not in unavailable[doc.id] and sat_str not in unavailable[doc.id]:
                assigned = doc
                break

        if assigned:
            weekend_assigned[fri_str] = assigned.id
            weekend_assigned[sat_str] = assigned.id
            weekend_count[assigned.id] += 1
            total_oncall_count[assigned.id] += 1  # each weekend unit = 1 total oncall
            entries.append({"date_str": fri_str, "entry_type": "oncall", "doctor_id": assigned.id})
            entries.append({"date_str": sat_str, "entry_type": "oncall", "doctor_id": assigned.id})
        else:
            alerts.append(f"לא נמצא כונן זמין לסוף שבוע {fri_str}")
            entries.append({"date_str": fri_str, "entry_type": "oncall", "doctor_id": None})
            entries.append({"date_str": sat_str, "entry_type": "oncall", "doctor_id": None})

    # Weekday on-call assignment
    # Sort by total on-calls (weekday + weekend) so weekend duty reduces weekday load
    for d in weekday_oncall_days_all:
        date_str = d.strftime("%Y-%m-%d")

        candidates = sorted(
            oncall_doctors,
            key=lambda doc: (
                date_str in unavailable[doc.id],
                total_oncall_count[doc.id],  # fewest total oncalls first
                -(date_str in preferred[doc.id])
            )
        )

        assigned = None
        for doc in candidates:
            if date_str not in unavailable[doc.id]:
                assigned = doc
                break

        if assigned:
            total_oncall_count[assigned.id] += 1
            entries.append({"date_str": date_str, "entry_type": "oncall", "doctor_id": assigned.id})
        else:
            alerts.append(f"לא נמצא כונן זמין ליום {date_str}")
            entries.append({"date_str": date_str, "entry_type": "oncall", "doctor_id": None})

    # ── SESSION SCHEDULING ──────────────────────────────────────────────────

    session_days = [d for d in days if is_session_day(d, holiday_set)]

    # Build session budgets (requested count per doctor)
    session_budget = {}
    session_assigned_count = defaultdict(int)
    session_hist = {d.id: session_counts[d.id]["sessions"] for d in session_doctors}

    num_session_days = len(session_days)
    for doc in session_doctors:
        r = req_by_doctor.get(doc.id)
        if r and r.desired_sessions is not None and r.desired_sessions > 0:
            session_budget[doc.id] = r.desired_sessions
        else:
            # No request or no preference — give a fair default share
            session_budget[doc.id] = max(1, round(num_session_days * 2 / max(len(session_doctors), 1)))

    for day in session_days:
        date_str = day.strftime("%Y-%m-%d")
        slots_filled = []

        # Two passes: first preferred, then fill remaining
        # Available doctors = has budget left and not unavailable
        available = [
            doc for doc in session_doctors
            if session_assigned_count[doc.id] < session_budget[doc.id]
            and date_str not in unavailable_session[doc.id]
        ]

        # Sort: prefer doctors who prefer this date, then by (assigned/budget ratio) asc
        def sort_key(doc):
            ratio = session_assigned_count[doc.id] / max(session_budget[doc.id], 1)
            return (
                -(date_str in preferred_session[doc.id]),
                ratio,
                session_hist[doc.id]
            )

        available_sorted = sorted(available, key=sort_key)

        for doc in available_sorted[:2]:
            slots_filled.append(doc.id)
            session_assigned_count[doc.id] += 1

        # Fill up to 2 slots
        slot_types = ["session1", "session2"]
        for i, slot_type in enumerate(slot_types):
            doctor_id = slots_filled[i] if i < len(slots_filled) else None
            if doctor_id is None:
                alerts.append(f"לא נמצא רופא לססיה {slot_type} בתאריך {date_str}")
            entries.append({"date_str": date_str, "entry_type": slot_type, "doctor_id": doctor_id})

    return {"entries": entries, "alerts": alerts}


def save_schedule_to_history(year, month, db, ScheduleEntry, HistoryEntry, Doctor):
    """
    After publishing, count each doctor's assignments and save to HistoryEntry.
    Weekend on-calls = Fri, Sat, holidays, holiday eves (each counted as 1).
    Weekday on-calls = Sun-Thu that are not holidays/eves.
    """
    from datetime import date as dt
    holiday_set = get_israeli_holidays(year)
    all_entries = ScheduleEntry.query.filter_by(month=month, year=year).all()
    all_doctors = Doctor.query.all()

    for doc in all_doctors:
        weekday_oncalls = 0
        weekend_oncalls = 0
        sessions = 0

        for e in all_entries:
            if e.doctor_id != doc.id:
                continue
            d = dt.fromisoformat(e.date_str)
            if e.entry_type == "oncall":
                is_special = d.weekday() in (4, 5) or e.date_str in holiday_set
                if is_special:
                    weekend_oncalls += 1
                else:
                    weekday_oncalls += 1
            elif e.entry_type in ("session1", "session2"):
                sessions += 1

        if weekday_oncalls + weekend_oncalls + sessions == 0:
            continue

        existing = HistoryEntry.query.filter_by(
            doctor_id=doc.id, month=month, year=year
        ).first()
        if existing:
            existing.weekday_oncalls = weekday_oncalls
            existing.weekend_oncalls = weekend_oncalls
            existing.sessions = sessions
        else:
            db.session.add(HistoryEntry(
                doctor_id=doc.id, month=month, year=year,
                weekday_oncalls=weekday_oncalls,
                weekend_oncalls=weekend_oncalls,
                sessions=sessions
            ))

    db.session.commit()
