"""Mercado Pago 'Resumen de cuenta' PDF (mobile export).

PyMuPDF extracts one text fragment per line for these exports; each movement is
a block: date (alone), description line(s), numeric reference id, $ amount, $ balance.
"""

from __future__ import annotations

import re
from io import BytesIO

from app.parsers import register
from app.parsers.mercadopago_common import mp_date_to_iso, parse_argentine_amount
from app.parsers.pdf_text import extract_pdf_text
from app.schemas import ParseResult, ParseRow

_DATE_ONLY = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_REF_ID = re.compile(r"^\d{10,}$")

_SKIP_LINE_PREFIXES = (
    "RESUMEN DE CUENTA",
    "DETALLE DE MOVIMIENTOS",
    "Fecha",
    "ID de la",
    "CVU:",
    "CUIT",
    "Periodo:",
    "Saldo inicial:",
    "Saldo final:",
    "Mercado Libre",
    "Encuentra nuestros",
    "www.mercadopago",
)

_SKIP_SUBSTRINGS = (
    "Fecha de generación",
    "Fecha de generacion",
)


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if re.match(r"^\d+/\d+$", s):
        return True
    if s.startswith("-- ") and s.endswith(" --"):
        return True
    for p in _SKIP_LINE_PREFIXES:
        if s.startswith(p):
            return True
    for sub in _SKIP_SUBSTRINGS:
        if sub in s:
            return True
    # Header row fragments
    if s in ("operación", "operacion", "Valor", "Saldo", "Descripción", "Descripcion"):
        return True
    if s.startswith("Del ") and "febrero" in s.lower():
        return True
    if s.startswith("Salidas:") or s.startswith("Entradas:"):
        return True
    return False


def _iter_movement_blocks(lines: list[str]) -> list[tuple[str, str, str, str, str]]:
    """Return list of (date_raw, description, ref_id, amount_raw, balance_raw)."""
    out: list[tuple[str, str, str, str, str]] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()
        i += 1
        if _is_noise_line(line):
            continue
        if not _DATE_ONLY.match(line):
            continue
        date_raw = line
        desc_parts: list[str] = []
        ref: str | None = None
        # description + optional continuation until reference id
        while i < n:
            s = lines[i].strip()
            if _is_noise_line(s):
                i += 1
                continue
            if _DATE_ONLY.match(s):
                i -= 1  # retry this date on outer loop; drop incomplete block
                ref = None
                break
            if _REF_ID.match(s):
                ref = s
                i += 1
                break
            desc_parts.append(s)
            i += 1
        else:
            continue
        if ref is None:
            continue
        if i >= n:
            break
        amt_line = lines[i].strip()
        i += 1
        if i >= n:
            break
        bal_line = lines[i].strip()
        i += 1
        if not amt_line.startswith("$") or not bal_line.startswith("$"):
            continue
        desc = " ".join(" ".join(desc_parts).split())
        out.append((date_raw, desc, ref, amt_line, bal_line))

    return out


@register("mercadopago", "pdf")
def parse_mercadopago_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    warnings: list[str] = []
    text = extract_pdf_text(buf)
    raw_lines = text.splitlines()
    blocks = _iter_movement_blocks(raw_lines)

    rows_out: list[ParseRow] = []
    dates: list[str] = []

    for date_raw, desc, ref, amt_line, _bal_line in blocks:
        d = mp_date_to_iso(date_raw)
        if not d:
            continue
        txn_amt = parse_argentine_amount(amt_line)
        if txn_amt is None:
            continue
        if txn_amt >= 0:
            continue
        rows_out.append(
            ParseRow(
                date=d,
                description=desc,
                amount=abs(txn_amt),
                currency="ARS",
                raw={"reference_id": ref, "source": "mercadopago_pdf"},
            )
        )
        dates.append(d)

    if "mercadopago" not in text.lower() and "Mercado Libre" not in text:
        warnings.append("PDF may not be a Mercado Pago export (no footer watermark text).")

    if not rows_out:
        warnings.append("No expense rows extracted from PDF; check export format.")

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    return ParseResult(
        rows=rows_out,
        warnings=warnings,
        bank_code=bank_code,
        file_type="pdf",
        currency="ARS",
        period=period,
    )
