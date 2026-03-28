"""
Banco Patagonia — Visa / credit card summary (e.g. ComprobanteBP PDF).

Transaction lines use DD.MM.YY, optional 6-digit + * or K comprobante, ARS amount at end
(thousands '.', decimal ','; trailing '-' = credit / payment).
"""

import re
from io import BytesIO

from app.parsers import register
from app.parsers.pdf_text import extract_pdf_text
from app.schemas import ParseResult, ParseRow

_SKIP_SUBSTR = (
    "SALDO ANTERIOR",
    "SU PAGO EN PESOS",
    "SU PAGO EN USD",
    "Total Consumos",
    "TARJETA",
    "DEBITAREMOS",
    "PAGO MINIMO",
    "LIMITES:",
)


def _patagonia_date_to_iso(d: str, m: str, y: str) -> str:
    yy = int(y)
    year = 2000 + yy if yy < 70 else 1900 + yy
    return f"{year:04d}-{m}-{d}"


def _parse_amount_ar(s: str) -> float | None:
    neg = s.endswith("-")
    s = s.rstrip("-").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _parse_line(line: str) -> ParseRow | None:
    s = line.rstrip()
    for sub in _SKIP_SUBSTR:
        if sub in s:
            return None
    m = re.match(r"^\s*(\d{2})\.(\d{2})\.(\d{2})\s+", s)
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    rest = s[m.end() :]
    m_amt = re.search(r"(\d[\d\.]*,\d{2})(-?)\s*$", rest)
    if not m_amt:
        return None
    amt = _parse_amount_ar(m_amt.group(1) + (m_amt.group(2) or ""))
    if amt is None:
        return None
    middle = rest[: m_amt.start()].strip()
    middle = re.sub(r"^\d{6}[\*K]\s+", "", middle).strip()
    if not middle or len(middle) < 2:
        return None
    date_iso = _patagonia_date_to_iso(d, mo, y)
    return ParseRow(
        date=date_iso,
        description=re.sub(r"\s+", " ", middle)[:500],
        amount=abs(amt),
        raw={"line": line.strip()},
    )


@register("patagonia", "pdf")
@register("bancopatagonia", "pdf")
@register("bp", "pdf")
def parse_patagonia_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    text = extract_pdf_text(buf)
    rows: list[ParseRow] = []
    dates: list[str] = []
    for line in text.splitlines():
        row = _parse_line(line)
        if row:
            rows.append(row)
            dates.append(row.date)
    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    warnings: list[str] = []
    if not rows:
        warnings.append(
            "No Patagonia-style rows found (expected DD.MM.YY lines with amounts). "
            "Try bank 'generic' or check the PDF format."
        )
    return ParseResult(
        rows=rows,
        warnings=warnings,
        bank_code=bank_code,
        file_type="pdf",
        period=period,
        currency="ARS",
    )
