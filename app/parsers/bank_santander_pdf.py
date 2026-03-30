"""
Santander Río — Visa resumen (Spanish month names + English in CIERRE).

Each detail line starts with a row index, then Spanish month, then the calendar day (1–31),
then comprobante + ref + description + ARS amount (or continuation lines with day + comprobante).

Year comes from "CIERRE … 19 Mar 26" (English month abbrev supported). If the transaction month
is after the closing month (e.g. Oct/Nov on a statement that closes in Mar), use closing year − 1.

Currency per row:
  - ARS lines: emitted with currency=None (inherits "ARS" from ParseResult).
  - USD / foreign-currency lines: emitted with currency="USD".
    The parser tries to extract the USD amount from patterns like "USD 15.99" or "U$S 15,99".
    Continuation USD lines (e.g. "  15 USD 15.99") are parsed similarly.

Repeated pages in the same PDF are deduped by (date, amount, currency, description[:200]).
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

# Row index, Spanish month, calendar day, rest (comprobante * desc or "IIBB …" without * ref)
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

# Matches USD or U$S followed by a numeric amount: "USD 15.99" / "U$S 1,234.56" / "USD 15,99"
_USD_MARKER = re.compile(r"(?:USD|U\$S)\s+([\d,\.]+)", re.IGNORECASE)


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


def _parse_usd_amount(raw_token: str) -> float | None:
    """Parse a numeric token that follows USD/U$S.

    Handles:
      "15.99"       → 15.99
      "1,234.56"    → 1234.56  (US comma-thousands)
      "15,99"       → 15.99   (European-style decimal)
      "1.234,56"    → 1234.56 (AR format, unusual for USD but possible)
    """
    s = raw_token.strip()
    if not s:
        return None
    if "," in s and "." in s:
        # Determine which is thousands vs decimal by position of last separator
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_dot > last_comma:
            # US format: 1,234.56
            clean = s.replace(",", "")
        else:
            # AR format: 1.234,56
            clean = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        # Could be 15,99 (European) or 1,234 (US thousands without decimal)
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            # Treat as decimal: 15,99 → 15.99
            clean = s.replace(",", ".")
        else:
            clean = s.replace(",", "")
    else:
        clean = s  # plain 15.99 or 15

    try:
        v = float(clean)
        return v if v > 0 else None
    except ValueError:
        return None


def _try_parse_usd(rest: str) -> tuple[str, float] | None:
    """Extract description and USD amount from a line that contains USD/U$S.

    Returns (description, usd_amount) or None if not parseable.
    """
    m = _USD_MARKER.search(rest)
    if not m:
        return None
    amount = _parse_usd_amount(m.group(1))
    if amount is None or amount < 0.01:
        return None
    # Description is everything before the USD marker
    desc_raw = rest[: m.start()].rstrip()
    # Strip comprobante prefix (e.g. "006328 * " or "006328K ")
    desc_raw = re.sub(r"^\d{5,7}\s*[\*K]?\s*", "", desc_raw).strip()
    # Strip a leading single-char reference letter
    desc_raw = re.sub(r"^[A-Z]\s+", "", desc_raw).strip()
    desc = re.sub(r"\s+", " ", desc_raw).strip()
    if len(desc) < 2:
        return None
    return desc, amount


def _skip_line(line: str) -> bool:
    if not line.strip() or line.strip().startswith("_"):
        return True
    u = line.upper()
    for sub in _SKIP_SUBSTR:
        if sub.upper() in u or sub in line:
            return True
    return False


def _is_usd_line(raw: str, rest: str | None = None) -> bool:
    """Returns True if this line carries a USD/U$S amount (foreign currency)."""
    combined = raw + " " + (rest or "")
    return bool(_USD_MARKER.search(combined))


def _is_payment_or_skip(raw: str) -> bool:
    """Returns True for lines that should be skipped entirely (payments, summaries, etc.)."""
    u = raw.upper()
    if "SU PAGO" in u:
        return True
    for sub in _SKIP_SUBSTR:
        if sub.upper() in u:
            return True
    return False


def _split_desc_amount_ars(rest: str) -> tuple[str, float] | None:
    """Parse ARS amount from line rest (ignores USD content)."""
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


def _emit_row(
    iso: str,
    desc: str,
    amt: float,
    raw_line: str,
    currency: str | None,
    seen: set,
    rows: list,
    dates: list,
) -> None:
    """Append a ParseRow if not already seen (deduplication)."""
    key = (iso, amt, currency or "ARS", desc[:200])
    if key in seen:
        return
    seen.add(key)
    rows.append(ParseRow(date=iso, description=desc[:500], amount=amt, currency=currency, raw={"line": raw_line}))
    dates.append(iso)


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
    seen: set[tuple[str, float, str, str]] = set()

    for line in lines:
        if _skip_line(line):
            continue

        raw = line.rstrip()

        # ── FULL line: row-index  Month  day  rest ──────────────────────────────
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
            iso = f"{y4:04d}-{mo:02d}-{cal_day:02d}"

            if _is_payment_or_skip(raw):
                continue

            if _is_usd_line(raw, rest):
                # Try to extract USD amount
                usd_parsed = _try_parse_usd(rest)
                if usd_parsed:
                    desc, amt = usd_parsed
                    _emit_row(iso, desc, amt, raw, "USD", seen, rows, dates)
                # Don't also emit ARS for USD lines — they're dual-currency display rows
                continue

            # ARS line
            split = _split_desc_amount_ars(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            _emit_row(iso, desc, amt, raw, None, seen, rows, dates)
            continue

        # ── CONT line: spaces  day  comprobante  rest ───────────────────────────
        cm_match = _CONT.match(raw)
        if cm_match and last_resolved is not None:
            d_s, _comp, _ref, rest = cm_match.groups()
            if _is_payment_or_skip(raw):
                continue

            y4, mo, _ = last_resolved
            dday = int(d_s)
            iso = f"{y4:04d}-{mo:02d}-{dday:02d}"

            if _is_usd_line(raw, rest):
                usd_parsed = _try_parse_usd(rest)
                if usd_parsed:
                    desc, amt = usd_parsed
                    _emit_row(iso, desc, amt, raw, "USD", seen, rows, dates)
                continue

            split = _split_desc_amount_ars(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            _emit_row(iso, desc, amt, raw, None, seen, rows, dates)
            continue

        # ── CONT_PLAIN line: spaces  day  text (no comprobante) ─────────────────
        pm = _CONT_PLAIN.match(raw)
        if pm and last_resolved is not None:
            d_s, rest = pm.groups()
            if _is_payment_or_skip(raw):
                continue

            y4, mo, _ = last_resolved
            dday = int(d_s)
            iso = f"{y4:04d}-{mo:02d}-{dday:02d}"

            if _is_usd_line(raw, rest):
                usd_parsed = _try_parse_usd(rest)
                if usd_parsed:
                    desc, amt = usd_parsed
                    _emit_row(iso, desc, amt, raw, "USD", seen, rows, dates)
                continue

            split = _split_desc_amount_ars(rest)
            if not split:
                continue
            desc, amt = split
            if len(desc) < 2:
                continue
            _emit_row(iso, desc, amt, raw, None, seen, rows, dates)

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    warnings: list[str] = []
    if not rows:
        warnings.append(
            "No Santander Río-style rows found. Expected 'DD Mes YY comprobante * … amount' lines "
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
