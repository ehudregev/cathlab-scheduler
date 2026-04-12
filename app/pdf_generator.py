from fpdf import FPDF
import calendar

MONTH_NAMES_HE = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
]

DAY_NAMES_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def reverse_hebrew(text):
    """FPDF renders RTL text reversed. This helper reverses Hebrew strings."""
    if not text:
        return ""
    return text[::-1]


class SchedulePDF(FPDF):
    def __init__(self, month_name, year):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.month_name = month_name
        self.year = year
        self.set_margins(10, 10, 10)
        self.set_auto_page_break(False)

    def header(self):
        self.set_font("Helvetica", "B", 16)
        title = f"{self.year} {self.month_name[::-1]}"
        self.cell(0, 10, f"{title}   -   {'::-1'[::-1]}", ln=True, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


def generate_pdf(year, month, month_name, days, holiday_set, entry_map, doctors):
    """Generate and return PDF bytes for the monthly schedule."""

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 8, 8)

    # Title
    pdf.set_font("Helvetica", "B", 14)
    title = f"Cathlab Schedule - {month_name[::-1]} {year}"
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.ln(2)

    # Table headers
    col_widths = {"date": 22, "day": 22, "oncall": 60, "sess1": 60, "sess2": 60}
    total_w = sum(col_widths.values())

    pdf.set_fill_color(50, 100, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)

    headers = [
        ("date", "Date"),
        ("day", "Day"),
        ("oncall", "On-Call"),
        ("sess1", "Session 1"),
        ("sess2", "Session 2"),
    ]

    for key, label in headers:
        pdf.cell(col_widths[key], 7, label, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)

    row_h = 7

    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        is_holiday = date_str in holiday_set
        is_weekend = day.weekday() in (4, 5)

        oncall_e = entry_map.get((date_str, "oncall"))
        sess1_e = entry_map.get((date_str, "session1"))
        sess2_e = entry_map.get((date_str, "session2"))

        def doctor_name(entry):
            if not entry or not entry.doctor_id:
                return "---"
            doc = doctors.get(entry.doctor_id)
            return doc.name if doc else "---"

        if is_holiday:
            pdf.set_fill_color(255, 220, 150)
            fill = True
        elif is_weekend:
            pdf.set_fill_color(200, 220, 255)
            fill = True
        else:
            pdf.set_fill_color(255, 255, 255)
            fill = True

        day_name = DAY_NAMES_HE[day.weekday()]
        note = " (chag)" if is_holiday else ""

        pdf.cell(col_widths["date"], row_h, day.strftime("%d/%m"), border=1, align="C", fill=fill)
        pdf.cell(col_widths["day"], row_h, day_name[::-1] + note[::-1], border=1, align="C", fill=fill)
        pdf.cell(col_widths["oncall"], row_h, doctor_name(oncall_e), border=1, align="C", fill=fill)

        # Sessions only on session days
        if not is_weekend and not is_holiday:
            pdf.cell(col_widths["sess1"], row_h, doctor_name(sess1_e), border=1, align="C", fill=fill)
            pdf.cell(col_widths["sess2"], row_h, doctor_name(sess2_e), border=1, align="C", fill=fill)
        else:
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(col_widths["sess1"], row_h, "---", border=1, align="C", fill=True)
            pdf.cell(col_widths["sess2"], row_h, "---", border=1, align="C", fill=True)
            # restore fill
            if is_holiday:
                pdf.set_fill_color(255, 220, 150)
            elif is_weekend:
                pdf.set_fill_color(200, 220, 255)

        pdf.ln()

    return bytes(pdf.output())
