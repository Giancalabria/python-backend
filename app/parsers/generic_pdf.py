import re
from io import BytesIO

import fitz

from app.parsers import register
from app.schemas import ParseResult, ParseRow

_LINE_RE = re.compile(
    r"(?P<d>\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+(?P<desc>.+?)\s+(?P<amt>[-]?\d[\d.,]*\d|\d)\s*$"
)


def _norm_date(s: str) -> str | None:
    s = s.strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    return None


def _parse_amt(s: str) -> float | None:
    s = s.replace(".", "").replace(",", ".") if "," in s else s.replace(",", "")
    try:
        return abs(float(s))
    except ValueError:
        return None


@register("generic", "pdf")
def parse_generic_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    warnings = [
        "Generic PDF parser: best-effort line detection. Add a bank-specific parser for production statements.",
    ]
    doc = fitz.open(stream=buf.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() or ""
    doc.close()

    rows_out: list[ParseRow] = []
    dates: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        d = _norm_date(m.group("d"))
        if not d:
            continue
        amt = _parse_amt(m.group("amt"))
        if amt is None:
            continue
        desc = m.group("desc").strip()
        rows_out.append(ParseRow(date=d, description=desc, amount=amt, raw={"line": line}))
        dates.append(d)

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    return ParseResult(
        rows=rows_out,
        warnings=warnings,
        bank_code=bank_code,
        file_type="pdf",
        period=period,
    )
