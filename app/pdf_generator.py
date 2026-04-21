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
