from fpdf import FPDF
from bidi.algorithm import get_display
import os

MONTH_NAMES_HE = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
]

DAY_NAMES_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Heebo.ttf")


def bidi(text):
    """Convert Hebrew/mixed text to visual (LTR-rendered) order for fpdf2."""
    if not text:
        return ""
    return get_display(str(text))


def generate_pdf(year, month, month_name, days, holiday_set, entry_map, doctors):
    """Generate and return PDF bytes for the monthly schedule."""

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_font("Heebo", style="", fname=FONT_PATH)
    pdf.add_font("Heebo", style="B", fname=FONT_PATH)
    pdf.add_page()
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 8, 8)

    # Title
    pdf.set_font("Heebo", "B", 14)
    title = bidi(f"לוח כוננויות וססיות — {month_name} {year}")
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)

    # Column widths
    col_widths = {"date": 22, "day": 22, "oncall": 60, "sess1": 60, "sess2": 60}

    # Table header
    pdf.set_fill_color(50, 100, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Heebo", "B", 9)

    headers = [
        ("date",   "תאריך"),
        ("day",    "יום"),
        ("oncall", "כונן"),
        ("sess1",  "ססיה 1"),
        ("sess2",  "ססיה 2"),
    ]

    for key, label in headers:
        pdf.cell(col_widths[key], 7, bidi(label), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Heebo", "", 9)

    # Dynamic row height: fit all days on one page (A4 landscape = 210mm height)
    # Fixed overhead: 8 top margin + 10 title cell + 2 ln + 7 header = 27mm
    row_h = min(7, (210 - 27) / max(len(days), 1))

    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        is_holiday = date_str in holiday_set
        is_weekend = day.weekday() in (4, 5)

        oncall_e = entry_map.get((date_str, "oncall"))
        sess1_e  = entry_map.get((date_str, "session1"))
        sess2_e  = entry_map.get((date_str, "session2"))

        def doctor_name(entry):
            if not entry or not entry.doctor_id:
                return "—"
            doc = doctors.get(entry.doctor_id)
            return bidi(doc.name) if doc else "—"

        if is_holiday:
            pdf.set_fill_color(255, 220, 150)
        elif is_weekend:
            pdf.set_fill_color(200, 220, 255)
        else:
            pdf.set_fill_color(245, 245, 245)

        day_name = DAY_NAMES_HE[day.weekday()]
        note = bidi(" חג") if is_holiday else ""

        pdf.cell(col_widths["date"],   row_h, day.strftime("%d/%m"),          border=1, align="C", fill=True)
        pdf.cell(col_widths["day"],    row_h, bidi(day_name) + note,          border=1, align="C", fill=True)
        pdf.cell(col_widths["oncall"], row_h, doctor_name(oncall_e),          border=1, align="C", fill=True)

        if not is_weekend and not is_holiday:
            pdf.cell(col_widths["sess1"], row_h, doctor_name(sess1_e), border=1, align="C", fill=True)
            pdf.cell(col_widths["sess2"], row_h, doctor_name(sess2_e), border=1, align="C", fill=True)
        else:
            pdf.set_fill_color(230, 230, 230)
            pdf.cell(col_widths["sess1"], row_h, "—", border=1, align="C", fill=True)
            pdf.cell(col_widths["sess2"], row_h, "—", border=1, align="C", fill=True)

        pdf.ln()

    return bytes(pdf.output())


def _initials(name):
    """Return initials of a Hebrew name: first letter of each word joined with periods."""
    words = name.strip().split()
    return ".".join(w[0] for w in words if w) + "." if words else ""


def generate_availability_pdf(year, month, month_name, days, holiday_set,
                               oncall_doctors, session_doctors, req_by_doctor):
    """
    PDF table: rows = days of month, columns = כוננות / ססיה.
    Each cell lists initials of doctors available for assignment that day.
    Weekends (Fri/Sat) are highlighted in blue.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("Heebo", style="", fname=FONT_PATH)
    pdf.add_font("Heebo", style="B", fname=FONT_PATH)
    pdf.add_page()
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 8, 8)

    # Title
    pdf.set_font("Heebo", "B", 13)
    pdf.cell(0, 10, bidi(f"זמינות לשיבוץ — {month_name} {year}"),
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)

    # Column widths  (A4 portrait = 210mm, margins 8+8)
    usable = 194  # 210 - 16
    col_date = 28
    col_content = (usable - col_date) / 2

    # Header
    pdf.set_fill_color(50, 100, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Heebo", "B", 9)
    for label, w in [(bidi("תאריך"), col_date),
                     (bidi("כוננות"), col_content),
                     (bidi("ססיה"),   col_content)]:
        pdf.cell(w, 7, label, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Heebo", "", 8)

    # Fit all days on one page (A4 portrait height 297mm, overhead ~27mm, bottom margin 8mm)
    row_h = min(7.5, (297 - 27 - 8) / max(len(days), 1))

    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        is_weekend = day.weekday() in (4, 5)
        is_holiday = date_str in holiday_set

        if is_holiday:
            pdf.set_fill_color(255, 220, 150)
        elif is_weekend:
            pdf.set_fill_color(200, 220, 255)
        else:
            pdf.set_fill_color(245, 245, 245)

        # Available oncall doctors
        oncall_names = []
        for doc in oncall_doctors:
            r = req_by_doctor.get(doc.id)
            unavail = r.unavailable_oncall if r else set()
            if date_str not in unavail:
                oncall_names.append(_initials(doc.name))
        oncall_text = bidi(" ".join(oncall_names)) if oncall_names else bidi("—")

        # Available session doctors (sessions only on Sun–Thu non-holiday)
        if is_weekend:
            session_text = bidi("—")
        else:
            session_names = []
            for doc in session_doctors:
                r = req_by_doctor.get(doc.id)
                unavail = r.unavailable_session if r else set()
                if date_str not in unavail:
                    session_names.append(_initials(doc.name))
            session_text = bidi(" ".join(session_names)) if session_names else bidi("—")

        day_label = bidi(f"{day.strftime('%d/%m')} {DAY_NAMES_HE[day.weekday()]}")
        pdf.cell(col_date,    row_h, day_label,    border=1, align="C", fill=True)
        pdf.cell(col_content, row_h, oncall_text,  border=1, align="C", fill=True)
        pdf.cell(col_content, row_h, session_text, border=1, align="C", fill=True)
        pdf.ln()

    return bytes(pdf.output())


def generate_oncall_system_pdf(year, month, month_name, days, holiday_set, virtual_map, doctors, warnings=None):
    """Generate the fictitious 'oncall system input' PDF with swapped doctors."""

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_font("Heebo", style="", fname=FONT_PATH)
    pdf.add_font("Heebo", style="B", fname=FONT_PATH)
    pdf.add_page()
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 8, 8)

    # Title
    pdf.set_font("Heebo", "B", 14)
    title = bidi(f"לוח הזנות למערכת הכוננויות — {month_name} {year}")
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)

    # Warnings
    if warnings:
        pdf.set_font("Heebo", "", 8)
        pdf.set_text_color(180, 0, 0)
        for w in warnings:
            pdf.cell(0, 5, bidi(f"⚠ {w}"), new_x="LMARGIN", new_y="NEXT", align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    col_widths = {"date": 22, "day": 22, "oncall": 60, "sess1": 60, "sess2": 60}

    pdf.set_fill_color(100, 60, 160)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Heebo", "B", 9)

    headers = [
        ("date",   "תאריך"),
        ("day",    "יום"),
        ("oncall", "כונן"),
        ("sess1",  "ססיה 1"),
        ("sess2",  "ססיה 2"),
    ]
    for key, label in headers:
        pdf.cell(col_widths[key], 7, bidi(label), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Heebo", "", 9)

    row_h = min(7, (210 - 27) / max(len(days), 1))

    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        is_holiday = date_str in holiday_set
        is_weekend = day.weekday() in (4, 5)

        def doctor_name_from_map(d_str, etype):
            doc_id = virtual_map.get((d_str, etype))
            if not doc_id:
                return "—"
            doc = doctors.get(doc_id)
            return bidi(doc.name) if doc else "—"

        if is_holiday:
            pdf.set_fill_color(255, 220, 150)
        elif is_weekend:
            pdf.set_fill_color(200, 220, 255)
        else:
            pdf.set_fill_color(245, 245, 245)

        day_name = DAY_NAMES_HE[day.weekday()]
        note = bidi(" חג") if is_holiday else ""

        pdf.cell(col_widths["date"],   row_h, day.strftime("%d/%m"),                      border=1, align="C", fill=True)
        pdf.cell(col_widths["day"],    row_h, bidi(day_name) + note,                      border=1, align="C", fill=True)
        pdf.cell(col_widths["oncall"], row_h, doctor_name_from_map(date_str, "oncall"),    border=1, align="C", fill=True)

        if not is_weekend and not is_holiday:
            pdf.cell(col_widths["sess1"], row_h, doctor_name_from_map(date_str, "session1"), border=1, align="C", fill=True)
            pdf.cell(col_widths["sess2"], row_h, doctor_name_from_map(date_str, "session2"), border=1, align="C", fill=True)
        else:
            pdf.set_fill_color(230, 230, 230)
            pdf.cell(col_widths["sess1"], row_h, "—", border=1, align="C", fill=True)
            pdf.cell(col_widths["sess2"], row_h, "—", border=1, align="C", fill=True)

        pdf.ln()

    return bytes(pdf.output())
