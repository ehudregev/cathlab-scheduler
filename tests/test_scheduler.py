"""
Tests for the scheduling algorithm and core logic.
Run with: pytest tests/
"""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from app.scheduler import (
    get_israeli_holidays,
    get_month_days,
    is_session_day,
    get_weekend_units,
)


# ── Israeli holidays ─────────────────────────────────────────────────────────

def test_get_israeli_holidays_returns_set():
    holidays = get_israeli_holidays(2025)
    assert isinstance(holidays, set)
    assert len(holidays) > 0


def test_holiday_eve_included():
    """For every official holiday, the day before should also be in the set."""
    import holidays as holidays_lib
    il = holidays_lib.Israel(years=2025)
    our_set = get_israeli_holidays(2025)
    for d in il.keys():
        eve = d - timedelta(days=1)
        assert eve.strftime("%Y-%m-%d") in our_set, f"Eve of {d} not found"
        assert d.strftime("%Y-%m-%d") in our_set, f"Holiday {d} not found"


def test_holidays_are_date_strings():
    holidays = get_israeli_holidays(2025)
    for h in list(holidays)[:5]:
        assert len(h) == 10
        assert h[4] == "-" and h[7] == "-"


def test_holiday_set_larger_than_raw_holidays():
    """Our set should be larger than the raw holidays lib (eves added)."""
    import holidays as holidays_lib
    il = holidays_lib.Israel(years=2025)
    our_set = get_israeli_holidays(2025)
    assert len(our_set) >= len(il)


# ── Month days ────────────────────────────────────────────────────────────────

def test_get_month_days_count():
    days = get_month_days(2025, 1)
    assert len(days) == 31


def test_get_month_days_february_leap():
    days = get_month_days(2024, 2)
    assert len(days) == 29


def test_get_month_days_february_non_leap():
    days = get_month_days(2025, 2)
    assert len(days) == 28


def test_get_month_days_types():
    days = get_month_days(2025, 6)
    for d in days:
        assert isinstance(d, date)


# ── Session days ─────────────────────────────────────────────────────────────

def test_friday_is_not_session_day():
    friday = date(2025, 5, 2)
    assert friday.weekday() == 4
    assert not is_session_day(friday, set())


def test_saturday_is_not_session_day():
    saturday = date(2025, 5, 3)
    assert saturday.weekday() == 5
    assert not is_session_day(saturday, set())


def test_sunday_is_session_day():
    sunday = date(2025, 5, 4)
    assert sunday.weekday() == 6
    assert is_session_day(sunday, set())


def test_monday_is_session_day():
    monday = date(2025, 5, 5)
    assert monday.weekday() == 0
    assert is_session_day(monday, set())


def test_holiday_weekday_is_not_session_day():
    monday = date(2025, 5, 5)
    holiday_set = {monday.strftime("%Y-%m-%d")}
    assert not is_session_day(monday, holiday_set)


def test_holiday_eve_is_not_session_day():
    wednesday = date(2025, 5, 7)
    holiday_set = {wednesday.strftime("%Y-%m-%d")}
    assert not is_session_day(wednesday, holiday_set)


# ── Weekend units ─────────────────────────────────────────────────────────────

def test_weekend_units_count():
    days = get_month_days(2025, 5)
    units = get_weekend_units(days)
    # May 2025 has Fridays on: 2, 9, 16, 23, 30 → 5 weekend units
    assert len(units) == 5


def test_weekend_units_are_fri_sat_pairs():
    days = get_month_days(2025, 5)
    units = get_weekend_units(days)
    for fri, sat in units:
        assert fri.weekday() == 4
        assert sat.weekday() == 5
        assert (sat - fri).days == 1


# ── Helpers for integration tests ────────────────────────────────────────────

def make_doctor(id, name, does_oncall=True, does_sessions=False):
    doc = MagicMock()
    doc.id = id
    doc.name = name
    doc.does_oncall = does_oncall
    doc.does_sessions = does_sessions
    return doc


def make_request(doctor_id, unavailable=None, preferred=None, desired_sessions=None):
    req = MagicMock()
    req.doctor_id = doctor_id
    unavail_set = set(unavailable or [])
    prefer_set = set(preferred or [])
    req.unavailable_oncall = unavail_set
    req.unavailable_session = unavail_set
    req.preferred_oncall = prefer_set
    req.preferred_session = prefer_set
    req.desired_sessions = desired_sessions
    return req


def zero_counts(doctors):
    return {d.id: {"weekday_oncalls": 0, "weekend_oncalls": 0, "weekend_units": 0, "sessions": 0, "session1": 0}
            for d in doctors}


# ── Integration tests (schedule generation) ──────────────────────────────────

def test_generate_schedule_fills_all_oncall_slots():
    """Every day in the month should have an on-call entry."""
    from app.scheduler import generate_schedule

    oncall_docs = [make_doctor(i, f"Dr{i}", does_oncall=True) for i in range(1, 6)]

    db = MagicMock()

    def filter_by_side(**kwargs):
        mock = MagicMock()
        if kwargs.get("does_oncall"):
            mock.all.return_value = oncall_docs
        elif kwargs.get("does_sessions"):
            mock.all.return_value = []
        else:
            mock.all.return_value = []
        return mock

    Doctor = MagicMock()
    Doctor.query.filter_by.side_effect = filter_by_side

    Request = MagicMock()
    Request.query.filter_by.return_value.all.return_value = []

    HistoryEntry = MagicMock()
    ScheduleEntry = MagicMock()

    with patch("app.scheduler.get_cumulative_counts", return_value=zero_counts(oncall_docs)):
        result = generate_schedule(2025, 6, db, Doctor, Request, ScheduleEntry, HistoryEntry)

    oncall_entries = [e for e in result["entries"] if e["entry_type"] == "oncall"]
    assert len(oncall_entries) == 30  # June has 30 days


def test_generate_schedule_no_doctor_when_all_unavailable():
    """If all on-call doctors are unavailable on a day, slot is empty with alert."""
    from app.scheduler import generate_schedule

    oncall_docs = [make_doctor(i, f"Dr{i}", does_oncall=True) for i in range(1, 6)]
    requests = [make_request(i, unavailable=["2025-06-02"]) for i in range(1, 6)]

    db = MagicMock()

    def filter_by_side(**kwargs):
        mock = MagicMock()
        if kwargs.get("does_oncall"):
            mock.all.return_value = oncall_docs
        elif kwargs.get("does_sessions"):
            mock.all.return_value = []
        else:
            mock.all.return_value = requests
        return mock

    Doctor = MagicMock()
    Doctor.query.filter_by.side_effect = filter_by_side

    Request = MagicMock()
    Request.query.filter_by.return_value.all.return_value = requests

    HistoryEntry = MagicMock()
    ScheduleEntry = MagicMock()

    with patch("app.scheduler.get_cumulative_counts", return_value=zero_counts(oncall_docs)):
        result = generate_schedule(2025, 6, db, Doctor, Request, ScheduleEntry, HistoryEntry)

    assert len(result["alerts"]) > 0
    june2_oncall = next(
        (e for e in result["entries"]
         if e["date_str"] == "2025-06-02" and e["entry_type"] == "oncall"),
        None
    )
    assert june2_oncall is not None
    assert june2_oncall["doctor_id"] is None


def test_session_budget_not_exceeded():
    """Doctors should not be assigned more sessions than requested."""
    from app.scheduler import generate_schedule

    session_docs = [make_doctor(i, f"Dr{i}", does_oncall=False, does_sessions=True)
                    for i in range(1, 9)]
    requests = [make_request(i, desired_sessions=2) for i in range(1, 9)]

    db = MagicMock()

    def filter_by_side(**kwargs):
        mock = MagicMock()
        if kwargs.get("does_oncall"):
            mock.all.return_value = []
        elif kwargs.get("does_sessions"):
            mock.all.return_value = session_docs
        else:
            mock.all.return_value = requests
        return mock

    Doctor = MagicMock()
    Doctor.query.filter_by.side_effect = filter_by_side

    Request = MagicMock()
    Request.query.filter_by.return_value.all.return_value = requests

    HistoryEntry = MagicMock()
    ScheduleEntry = MagicMock()

    with patch("app.scheduler.get_cumulative_counts", return_value=zero_counts(session_docs)):
        result = generate_schedule(2025, 6, db, Doctor, Request, ScheduleEntry, HistoryEntry)

    session_count = {}
    for e in result["entries"]:
        if e["entry_type"] in ("session1", "session2") and e["doctor_id"]:
            session_count[e["doctor_id"]] = session_count.get(e["doctor_id"], 0) + 1

    for doc_id, count in session_count.items():
        assert count <= 2, f"Doctor {doc_id} got {count} sessions but max is 2"


def test_weekend_oncall_covers_both_days():
    """When a doctor is assigned weekend on-call, Friday and Saturday get the same doctor."""
    from app.scheduler import generate_schedule

    oncall_docs = [make_doctor(i, f"Dr{i}", does_oncall=True) for i in range(1, 6)]

    db = MagicMock()

    def filter_by_side(**kwargs):
        mock = MagicMock()
        if kwargs.get("does_oncall"):
            mock.all.return_value = oncall_docs
        else:
            mock.all.return_value = []
        return mock

    Doctor = MagicMock()
    Doctor.query.filter_by.side_effect = filter_by_side

    Request = MagicMock()
    Request.query.filter_by.return_value.all.return_value = []

    HistoryEntry = MagicMock()
    ScheduleEntry = MagicMock()

    with patch("app.scheduler.get_cumulative_counts", return_value=zero_counts(oncall_docs)):
        result = generate_schedule(2025, 5, db, Doctor, Request, ScheduleEntry, HistoryEntry)

    # May 2025: first weekend is Fri May 2, Sat May 3
    fri = next((e for e in result["entries"]
                if e["date_str"] == "2025-05-02" and e["entry_type"] == "oncall"), None)
    sat = next((e for e in result["entries"]
                if e["date_str"] == "2025-05-03" and e["entry_type"] == "oncall"), None)

    assert fri is not None
    assert sat is not None
    if fri["doctor_id"] and sat["doctor_id"]:
        assert fri["doctor_id"] == sat["doctor_id"]
