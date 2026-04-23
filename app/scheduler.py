"""
Scheduling algorithm for cathlab on-call and sessions.
"""
from datetime import date, timedelta
import calendar
import holidays as holidays_lib
from collections import defaultdict


def _max_run(date_strs):
    """Return the longest consecutive-calendar-day run in a set of date strings."""
    if not date_strs:
        return 0
    dates = sorted(date.fromisoformat(s) for s in date_strs)
    run = 1
    max_run = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days == 1:
            run += 1
            if run > max_run:
                max_run = run
        else:
            run = 1
    return max_run


def _run_after(existing, new_dates):
    """Max consecutive run after adding new_dates (iterable of str) to existing set."""
    return _max_run(existing | set(new_dates))


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


def get_cumulative_counts(doctors, month, year, _db, HistoryEntry, _ScheduleEntry):
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
            "weekend_units": sum(e.weekend_units or 0 for e in entries),
            "sessions": sum(e.sessions for e in entries),
            "session1": sum(e.session1_count for e in entries),
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
    # weekend_units = number of fri+sat pairs + holiday weekday oncalls (each counts as 1 unit)
    weekend_count = {d.id: oncall_counts[d.id]["weekend_units"] for d in oncall_doctors}
    total_oncall_count = {
        d.id: oncall_counts[d.id]["weekday_oncalls"] + oncall_counts[d.id]["weekend_units"]
        for d in oncall_doctors
    }

    num_weekends = len(weekend_units)
    num_oncall_docs = len(oncall_doctors)
    import math
    # Hard cap: no doctor gets more than ceil(weekends/doctors) unless forced
    weekend_cap = math.ceil(num_weekends / max(num_oncall_docs, 1)) if num_oncall_docs else 0

    # Precompute availability per weekend slot
    avail_per_slot = []
    for (fri, sat) in weekend_units:
        fri_s = fri.strftime("%Y-%m-%d")
        sat_s = sat.strftime("%Y-%m-%d")
        avail_per_slot.append([
            doc for doc in oncall_doctors
            if fri_s not in unavailable[doc.id] and sat_s not in unavailable[doc.id]
        ])

    # Flexibility: total weekends each doctor can do
    doc_weekend_availability = {
        doc.id: sum(1 for slot_docs in avail_per_slot if any(d.id == doc.id for d in slot_docs))
        for doc in oncall_doctors
    }

    # Exclusive slots: weekends where this doctor is the ONLY one available.
    # Doctors with more exclusive slots get LOWER priority on contested weekends
    # (their exclusive slots are guaranteed; don't let them crowd out others).
    doc_exclusive_slots = {
        doc.id: sum(1 for slot_docs in avail_per_slot if len(slot_docs) == 1 and slot_docs[0].id == doc.id)
        for doc in oncall_doctors
    }

    # Track assigned oncall dates per doctor for consecutive-day checking
    oncall_assigned = defaultdict(set)

    for (fri, sat) in weekend_units:
        fri_str = fri.strftime("%Y-%m-%d")
        sat_str = sat.strftime("%Y-%m-%d")

        # Hard exclude: not available OR would create 4+ consecutive days
        available = [
            doc for doc in oncall_doctors
            if fri_str not in unavailable[doc.id]
            and sat_str not in unavailable[doc.id]
            and _run_after(oncall_assigned[doc.id], {fri_str, sat_str}) < 4
        ]
        # Fallback: ignore consecutive constraint if it leaves no one
        if not available:
            available = [
                doc for doc in oncall_doctors
                if fri_str not in unavailable[doc.id] and sat_str not in unavailable[doc.id]
            ]
        if not available:
            alerts.append(f"לא נמצא כונן זמין לסוף שבוע {fri_str}")
            entries.append({"date_str": fri_str, "entry_type": "oncall", "doctor_id": None})
            entries.append({"date_str": sat_str, "entry_type": "oncall", "doctor_id": None})
            continue

        under_cap = [doc for doc in available if weekend_count[doc.id] < weekend_cap]
        pool = under_cap if under_cap else available

        pool.sort(key=lambda d: (
            weekend_count[d.id],
            doc_weekend_availability[d.id],
            doc_exclusive_slots[d.id],
            _run_after(oncall_assigned[d.id], {fri_str, sat_str}) >= 3,  # soft: avoid 3-run
            -(fri_str in preferred[d.id] or sat_str in preferred[d.id])
        ))

        assigned = pool[0]
        weekend_assigned[fri_str] = assigned.id
        weekend_assigned[sat_str] = assigned.id
        weekend_count[assigned.id] += 1
        total_oncall_count[assigned.id] += 1
        oncall_assigned[assigned.id].update({fri_str, sat_str})
        entries.append({"date_str": fri_str, "entry_type": "oncall", "doctor_id": assigned.id})
        entries.append({"date_str": sat_str, "entry_type": "oncall", "doctor_id": assigned.id})

    # Weekday on-call assignment
    for d in weekday_oncall_days_all:
        date_str = d.strftime("%Y-%m-%d")
        is_special = d.weekday() in (4, 5) or date_str in holiday_set

        # Hard exclude: not available OR would create 4+ consecutive days
        eligible = [
            doc for doc in oncall_doctors
            if date_str not in unavailable[doc.id]
            and _run_after(oncall_assigned[doc.id], {date_str}) < 4
        ]
        # Fallback: ignore consecutive constraint if it leaves no one
        if not eligible:
            eligible = [doc for doc in oncall_doctors if date_str not in unavailable[doc.id]]

        if is_special:
            candidates = sorted(eligible, key=lambda doc: (
                weekend_count[doc.id],
                total_oncall_count[doc.id],
                _run_after(oncall_assigned[doc.id], {date_str}) >= 3,  # soft: avoid 3-run
                -(date_str in preferred[doc.id])
            ))
        else:
            candidates = sorted(eligible, key=lambda doc: (
                total_oncall_count[doc.id],
                _run_after(oncall_assigned[doc.id], {date_str}) >= 3,  # soft: avoid 3-run
                -(date_str in preferred[doc.id])
            ))

        if candidates:
            assigned = candidates[0]
            total_oncall_count[assigned.id] += 1
            if is_special:
                weekend_count[assigned.id] += 1
            oncall_assigned[assigned.id].add(date_str)
            entries.append({"date_str": date_str, "entry_type": "oncall", "doctor_id": assigned.id})
        else:
            alerts.append(f"לא נמצא כונן זמין ליום {date_str}")
            entries.append({"date_str": date_str, "entry_type": "oncall", "doctor_id": None})

    # ── SESSION SCHEDULING ──────────────────────────────────────────────────

    session_days = [d for d in days if is_session_day(d, holiday_set)]

    # Build session budgets (requested count per doctor)
    session_budget = {}
    session_assigned_count = defaultdict(int)

    # Load cumulative session1 counts for balancing
    session_hist = get_cumulative_counts(session_doctors, month, year, db, HistoryEntry, ScheduleEntry)
    session1_so_far = {doc.id: session_hist[doc.id]["session1"] for doc in session_doctors}

    num_session_days = len(session_days)
    for doc in session_doctors:
        r = req_by_doctor.get(doc.id)
        if r and r.desired_sessions is not None and r.desired_sessions > 0:
            session_budget[doc.id] = r.desired_sessions
        else:
            # No request or no preference — give a fair default share
            session_budget[doc.id] = max(1, round(num_session_days * 2 / max(len(session_doctors), 1)))

    # Track sessions per doctor per ISO week and per day for constraints
    week_session_count = defaultdict(lambda: defaultdict(int))
    session_assigned_dates = defaultdict(set)  # for consecutive-day check

    for day in session_days:
        date_str = day.strftime("%Y-%m-%d")
        week_key = day.isocalendar()[:2]  # (year, iso_week)

        # Available doctors = has budget left and not unavailable
        available = [
            doc for doc in session_doctors
            if session_assigned_count[doc.id] < session_budget[doc.id]
            and date_str not in unavailable_session[doc.id]
        ]

        # Hard exclude: would create 3 consecutive session days
        no_consec = [d for d in available if _run_after(session_assigned_dates[d.id], {date_str}) < 3]
        if no_consec:
            available = no_consec

        def sort_key(doc):
            ratio = session_assigned_count[doc.id] / max(session_budget[doc.id], 1)
            return (
                -(date_str in preferred_session[doc.id]),
                ratio,
            )

        # Fill 2 slots with strict weekly cap:
        #   Tier 1: < 2 sessions this week (preferred)
        #   Tier 2: == 2 sessions this week (fallback — gives 3rd, allowed only if no other option)
        #   Tier 3: > 2 sessions this week (last resort)
        tier1 = [d for d in available if week_session_count[d.id][week_key] < 2]
        tier2 = [d for d in available if week_session_count[d.id][week_key] == 2]
        tier3 = [d for d in available if week_session_count[d.id][week_key] > 2]
        selected = sorted(tier1, key=sort_key)[:2]
        if len(selected) < 2:
            selected += sorted(tier2, key=sort_key)[:2 - len(selected)]
        if len(selected) < 2:
            selected += sorted(tier3, key=sort_key)[:2 - len(selected)]

        # If only one doctor available and it's דני אליאן, don't assign (needs a partner)
        if len(selected) == 1 and selected[0].name == "דני אליאן":
            selected = []
        for doc in selected:
            session_assigned_count[doc.id] += 1
            week_session_count[doc.id][week_key] += 1
            session_assigned_dates[doc.id].add(date_str)

        # Assign session1 to whichever of the two has fewer cumulative session1 assignments
        if len(selected) == 2:
            doc_a, doc_b = selected
            if session1_so_far[doc_a.id] <= session1_so_far[doc_b.id]:
                order = [doc_a.id, doc_b.id]
            else:
                order = [doc_b.id, doc_a.id]
            session1_so_far[order[0]] += 1
        else:
            order = [doc.id for doc in selected]

        # Fill up to 2 slots
        slot_types = ["session1", "session2"]
        for i, slot_type in enumerate(slot_types):
            doctor_id = order[i] if i < len(order) else None
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
        weekend_units = 0
        sessions = 0
        session1_count = 0

        for e in all_entries:
            if e.doctor_id != doc.id:
                continue
            d = dt.fromisoformat(e.date_str)
            if e.entry_type == "oncall":
                is_friday = d.weekday() == 4
                is_saturday = d.weekday() == 5
                is_holiday_weekday = e.date_str in holiday_set and not is_friday and not is_saturday
                if is_friday:
                    # Friday = one weekend unit (Saturday is paired and not counted separately)
                    weekend_oncalls += 1
                    weekend_units += 1
                elif is_saturday:
                    # Saturday is already counted with Friday
                    weekend_oncalls += 1
                elif is_holiday_weekday:
                    # Holiday on a regular weekday = special unit
                    weekend_oncalls += 1
                    weekend_units += 1
                else:
                    weekday_oncalls += 1
            elif e.entry_type == "session1":
                sessions += 1
                session1_count += 1
            elif e.entry_type == "session2":
                sessions += 1

        if weekday_oncalls + weekend_oncalls + sessions == 0:
            continue

        existing = HistoryEntry.query.filter_by(
            doctor_id=doc.id, month=month, year=year
        ).first()
        if existing:
            existing.weekday_oncalls = weekday_oncalls
            existing.weekend_oncalls = weekend_oncalls
            existing.weekend_units = weekend_units
            existing.sessions = sessions
            existing.session1_count = session1_count
        else:
            db.session.add(HistoryEntry(
                doctor_id=doc.id, month=month, year=year,
                weekday_oncalls=weekday_oncalls,
                weekend_oncalls=weekend_oncalls,
                weekend_units=weekend_units,
                sessions=sessions,
                session1_count=session1_count,
            ))

    db.session.commit()
