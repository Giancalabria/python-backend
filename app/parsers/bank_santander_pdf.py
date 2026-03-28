"""
Santander Río — Visa resumen (Spanish month names + English in CIERRE).

Each detail line starts with a row index, then Spanish month, then the calendar day (1–31),
then comprobante + ref + description + ARS amount (or continuation lines with day + comprobante).

Year comes from “CIERRE … 19 Mar 26” (English month abbrev supported). If the transaction month
is after the closing month (e.g. Oct/Nov on a statement that closes in Mar), use closing year − 1.

USD / dual-currency lines are skipped for import but still update the last resolved date so the
next continuation line attaches to the correct month.

Repeated pages in the same PDF are deduped by (date, amount, description).
"""

import re
from io import BytesIO

from app.parsers import register
from app.parsers.pdf_text import extract_pdf_text
from app.schemas import ParseResult, ParseRow

_MONTH_PREFIXES = (
    ("enero", 1),
    ("febrero", 2),
    ("marzo", 3),
    ("abril", 4),
    ("mayo", 5),
    ("junio", 6),
    ("julio", 7),
    ("agosto", 8),
    ("septiembre", 9),
    ("setiembre", 9),
    ("octubre", 10),
    ("noviembre", 11),
    ("noviem", 11),
    ("diciembre", 12),
    ("dic", 12),
)

_ARS_TAIL = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})(-?)\s*$")

# Row index, Spanish month, calendar day, rest (comprobante * desc or “IIBB …” without * ref)
_FULL = re.compile(r"^(\d{1,2})\s+(\w+\.?)\s+(\d{1,2})\s+(.+)$")

_CONT = re.compile(r"^\s+(\d{1,2})\s+(\d{5,7})\s*([\*K])?\s+(.+)$")
# Tax / footer lines: spaces, day, spaces, text (no comprobante)
_CONT_PLAIN = re.compile(r"^\s+(\d{1,2})\s{2,}([A-Za-zÁÉÍÓÚÑáéíóúñ].+)$")

_SKIP_SUBSTR = (
    "SALDO ANTERIOR",
    "SU PAGO",
    "CR.RG",
    "IIBB",
    "IVA RG",
    "DB.RG",
    "Tarjeta",
    "Total Consumos",
    "RESUMEN DE CUENTA",
    "Santander",
    "CUIT ",
    "LIMITES:",
    "Plan V.",
    "Cuotas a vencer",
    "EL PRESENTE ES COPIA",
    "PAGO MINIMO",
    "SALDO ACTUAL",
    "MACACHA",
    "SUPERCLUB",
)

_CIERRE = re.compile(
    r"CIERRE\s+(\d{1,2})\s+(\w+\.?)\s+(\d{2})",
    re.IGNORECASE,
)

# CIERRE uses English abbrevs (Mar); body lines use Spanish (Marzo).
_ENG3: dict[str, int] = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "aug": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
    "dec": 12,
}


def _month_from_token(tok: str) -> int | None:
    t = tok.lower().rstrip(".")
    for prefix, num in _MONTH_PREFIXES:
        if t.startswith(prefix):
            return num
    if len(t) >= 3:
        return _ENG3.get(t[:3])
    return None


def _year_4(yy: int) -> int:
    return 2000 + yy if yy < 70 else 1900 + yy


def _closing_year_month(text: str) -> tuple[int, int] | None:
    m = _CIERRE.search(text)
    if not m:
        return None
    _d, mon_tok, yy_s = m.group(1), m.group(2), m.group(3)
    mon = _month_from_token(mon_tok)
    if mon is None:
        return None
    return _year_4(int(yy_s)), mon


def _parse_ars_tail(s: str) -> tuple[str, float] | None:
    s = s.rstrip()
    m = _ARS_TAIL.search(s)
    if not m:
        return None
    body = s[: m.start()].rstrip()
    amt_s = m.group(1) + (m.group(2) or "")
    neg = amt_s.endswith("-")
    amt_s = amt_s.rstrip("-")
    num = amt_s.replace(".", "").replace(",", ".")
    try:
        v = float(num)
    except ValueError:
        return None
    if neg:
        v = -v
    desc = re.sub(r"\s+", " ", body).strip()
    return desc, abs(v)


def _skip_line(line: str) -> bool:
    if not line.strip() or line.strip().startswith("_"):
        return True
    u = line.upper()
    for sub in _SKIP_SUBSTR:
        if sub.upper() in u or sub in line:
            return True
    return False


def _skip_emission_raw(raw: str, rest: str | None = None) -> bool:
    """Skip row output (payments, USD lines, footers) but not date extraction on parent lines."""
    u = raw.upper()
    r = (rest or "").upper()
    if " USD " in u or " USD " in r:
        return True
    if " U$S" in u or " U$S" in r:
        return True
    if "SU PAGO" in u:
        return True
    if re.search(r"USD", raw, re.I) or (rest and re.search(r"USD", rest, re.I)):
        return True
    for sub in _SKIP_SUBSTR:
        if sub.upper() in u:
            return True
    return False


def _split_desc_amount(rest: str) -> tuple[str, float] | None:
    if " USD " in rest or re.search(r"USD", rest, re.I):
        return None
    parsed = _parse_ars_tail(rest)
    if not parsed:
        return None
    desc, amt = parsed
    if amt < 0.01:
        return None
    return desc, amt


def _calendar_date_from_closing(
    trans_month: int,
    day: int,
    closing: tuple[int, int] | None,
) -> tuple[int, int, int] | None:
    """Closing is (year4, month_of_closing). First number on the line is row index, not calendar day."""
    if closing is None or day < 1 or day > 31:
        return None
    cy, cm = closing
    y = cy - 1 if trans_month > cm else cy
    return y, trans_month, day


@register("santander", "pdf")
@register("santander_rio", "pdf")
def parse_santander_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    raw_bytes = buf.read()
    text = extract_pdf_text(BytesIO(raw_bytes))
    closing = _closing_year_month(text)
    lines = text.splitlines()

    last_resolved: tuple[int, int, int] | None = None  # y4, mon, day
    rows: list[ParseRow] = []
    dates: list[str] = []
    seen: set[tuple[str, float, str]] = set()

    for line in lines:
        if _skip_line(line):
            continue

        raw = line.rstrip()
        fm = _FULL.match(raw)
        if fm:
            _idx_s, mon_tok, day_s, rest = fm.groups()
            mon = _month_from_token(mon_tok)
            if mon is None:
                continue
            dday = int(day_s)
            resolved = _calendar_date_from_closing(mon, dday, closing)
            if resolved is None:
                continue
            y4, mo, cal_day = resolved
            last_resolved = (y4, mo, cal_day)
            if _skip_emission_raw(raw, rest):
                continue
            split = _split_desc_amount(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            iso = f"{y4:04d}-{mo:02d}-{cal_day:02d}"
            key = (iso, amt, desc[:200])
            if key in seen:
                continue
            seen.add(key)
            rows.append(ParseRow(date=iso, description=desc[:500], amount=amt, raw={"line": raw}))
            dates.append(iso)
            continue

        cm = _CONT.match(raw)
        if cm and last_resolved is not None:
            d_s, _comp, _ref, rest = cm.groups()
            if _skip_emission_raw(raw, rest):
                continue
            split = _split_desc_amount(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            y4, mo, _ = last_resolved
            dday = int(d_s)
            iso = f"{y4:04d}-{mo:02d}-{dday:02d}"
            key = (iso, amt, desc[:200])
            if key in seen:
                continue
            seen.add(key)
            rows.append(ParseRow(date=iso, description=desc[:500], amount=amt, raw={"line": raw}))
            dates.append(iso)
            continue

        pm = _CONT_PLAIN.match(raw)
        if pm and last_resolved is not None:
            d_s, rest = pm.groups()
            if _skip_emission_raw(raw, rest):
                continue
            split = _split_desc_amount(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            y4, mo, _ = last_resolved
            dday = int(d_s)
            iso = f"{y4:04d}-{mo:02d}-{dday:02d}"
            key = (iso, amt, desc[:200])
            if key in seen:
                continue
            seen.add(key)
            rows.append(ParseRow(date=iso, description=desc[:500], amount=amt, raw={"line": raw}))
            dates.append(iso)

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    warnings: list[str] = []
    if not rows:
        warnings.append(
            "No Santander Río-style rows found. Expected ‘DD Mes YY comprobante * … amount’ lines "
            "or use another bank / generic."
        )
    return ParseResult(
        rows=rows,
        warnings=warnings,
        bank_code=bank_code,
        file_type="pdf",
        period=period,
        currency="ARS",
    )
