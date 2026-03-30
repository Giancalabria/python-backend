"""
Banco Patagonia — Visa / credit card summary (e.g. ComprobanteBP PDF).

Transaction lines use DD.MM.YY, optional 6-digit + * or K comprobante, amount at end.

Currency detection:
  - Lines with an ARS amount tail (thousands '.', decimal ',') → currency=None (ARS).
  - Lines where the amount follows a "USD"/"U$S" marker → currency="USD".
  - "SU PAGO EN USD" and "SU PAGO EN PESOS" are payment lines and are always skipped.
  - Section headers "CARGOS EN DOLARES" / "DOLARES" switch the active currency to USD;
    "CARGOS EN PESOS" / "PESOS" switches back to ARS.
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
    "SU PAGO EN DOLARES",
    "Total Consumos",
    "TARJETA",
    "DEBITAREMOS",
    "PAGO MINIMO",
    "LIMITES:",
)

_SECTION_USD = re.compile(r"(CARGOS EN D[OÓ]LARES|D[OÓ]LARES)", re.I)
_SECTION_ARS = re.compile(r"(CARGOS EN PESOS|PESOS)", re.I)

# USD marker in a line: "USD 15.99" / "U$S 1,234.56"
_USD_MARKER = re.compile(r"(?:USD|U\$S)\s+([\d,\.]+)", re.IGNORECASE)


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


def _parse_usd_amount_token(raw_token: str) -> float | None:
    s = raw_token.strip()
    if not s:
        return None
    if "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        clean = s.replace(",", "") if last_dot > last_comma else s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        parts = s.split(",")
        clean = s.replace(",", ".") if len(parts) == 2 and len(parts[1]) <= 2 else s.replace(",", "")
    else:
        clean = s
    try:
        v = float(clean)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_line(line: str, section_currency: str | None) -> ParseRow | None:
    s = line.rstrip()
    for sub in _SKIP_SUBSTR:
        if sub in s:
            return None

    m = re.match(r"^\s*(\d{2})\.(\d{2})\.(\d{2})\s+", s)
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    rest = s[m.end():]

    # Check for USD marker in the line
    usd_m = _USD_MARKER.search(rest)
    if usd_m or section_currency == "USD":
        if usd_m:
            amount = _parse_usd_amount_token(usd_m.group(1))
            if amount is None or amount < 0.01:
                return None
            # Description: everything before the USD marker, minus comprobante
            desc_raw = rest[: usd_m.start()].strip()
            desc_raw = re.sub(r"^\d{6}[\*K]\s+", "", desc_raw).strip()
            if not desc_raw or len(desc_raw) < 2:
                return None
            return ParseRow(
                date=_patagonia_date_to_iso(d, mo, y),
                description=re.sub(r"\s+", " ", desc_raw)[:500],
                amount=amount,
                currency="USD",
                raw={"line": line.strip()},
            )
        else:
            # In a USD section without explicit USD marker — use ARS tail amount but tag as USD
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
            return ParseRow(
                date=_patagonia_date_to_iso(d, mo, y),
                description=re.sub(r"\s+", " ", middle)[:500],
                amount=abs(amt),
                currency="USD",
                raw={"line": line.strip()},
            )

    # ARS line
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
    return ParseRow(
        date=_patagonia_date_to_iso(d, mo, y),
        description=re.sub(r"\s+", " ", middle)[:500],
        amount=abs(amt),
        currency=None,  # ARS
        raw={"line": line.strip()},
    )


@register("patagonia", "pdf")
@register("bancopatagonia", "pdf")
@register("bp", "pdf")
def parse_patagonia_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    text = extract_pdf_text(buf)
    rows: list[ParseRow] = []
    dates: list[str] = []
    section_currency: str | None = None  # None = ARS

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Detect section header changes
        if _SECTION_USD.search(stripped) and not re.search(r"\d{2}\.\d{2}\.\d{2}", stripped):
            section_currency = "USD"
            continue
        if _SECTION_ARS.search(stripped) and not re.search(r"\d{2}\.\d{2}\.\d{2}", stripped):
            section_currency = None
            continue

        row = _parse_line(line, section_currency)
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
