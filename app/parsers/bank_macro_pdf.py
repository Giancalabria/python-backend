"""
Banco Macro — Visa credit card summary (Resumen PDF with CUIT 30-50000173-5 style).

Each movement is a multiline block: FECHA (DD-MM-YY), reference letter, description,
optional cuota (NN/NN), comprobante, amount in pesos (AR format).
"""

import re
from io import BytesIO

from app.parsers import register
from app.parsers.pdf_text import extract_pdf_text
from app.schemas import ParseResult, ParseRow

_DATE_LINE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")
_AMT_LINE = re.compile(r"^(-?)(\d[\d\.]*),(\d{2})\s*$")
_COMPROBANTE = re.compile(r"^\d{5,8}$")
_CUOTA = re.compile(r"^\d{1,2}/\d{1,2}$")
_SKIP_DESC = re.compile(
    r"^(DETALLE|FECHA|REFERENCIA|CUOTA|COMPROBANTE|PESOS|DÓLARES|DOLARES|TARJETA|CONSOLIDADO|Resumen|Tarjeta|Consumidor|CUIT|Sucursal|N°|Página)",
    re.I,
)


def _macro_date_to_iso(d: str, m: str, y: str) -> str:
    yy = int(y)
    year = 2000 + yy if yy < 70 else 1900 + yy
    return f"{year:04d}-{m}-{d}"


def _parse_amount_from_match(sign: str, intpart: str, dec: str) -> float:
    s = intpart.replace(".", "") + "." + dec
    v = float(s)
    return -v if sign == "-" else v


def _parse_macro_blocks(lines: list[str]) -> list[ParseRow]:
    rows: list[ParseRow] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i].strip()
        dm = _DATE_LINE.match(raw)
        if not dm:
            i += 1
            continue
        d, mo, y = dm.group(1), dm.group(2), dm.group(3)
        date_iso = _macro_date_to_iso(d, mo, y)
        i += 1
        chunk: list[str] = []
        while i < n:
            nxt = lines[i].strip()
            if _DATE_LINE.match(nxt):
                break
            if nxt:
                chunk.append(nxt)
            i += 1

        if not chunk:
            continue

        amt_idx = None
        for j in range(len(chunk) - 1, -1, -1):
            am = _AMT_LINE.match(chunk[j])
            if am:
                amt_idx = j
                break
        if amt_idx is None:
            continue

        sign, ip, dec = _AMT_LINE.match(chunk[amt_idx]).groups()
        amount = abs(_parse_amount_from_match(sign, ip, dec))

        before = chunk[:amt_idx]
        if not before:
            continue

        desc_parts: list[str] = []
        for p in before[1:]:
            if _COMPROBANTE.match(p) or _CUOTA.match(p):
                continue
            if len(p) <= 2 and p in ("K", "*", "D", "C"):
                continue
            if _SKIP_DESC.match(p):
                continue
            desc_parts.append(p)
        description = " ".join(desc_parts).strip()
        if not description or len(description) < 2:
            continue
        if "Total Consumos" in description or description.startswith("TARJETA"):
            continue
        if "SU PAGO" in description or "SALDO ANTERIOR" in description.upper():
            continue

        rows.append(
            ParseRow(
                date=date_iso,
                description=re.sub(r"\s+", " ", description)[:500],
                amount=amount,
                raw={"chunk": before + [chunk[amt_idx]]},
            )
        )
    return rows


@register("macro", "pdf")
@register("banco_macro", "pdf")
def parse_macro_pdf(buf: BytesIO, bank_code: str) -> ParseResult:
    text = extract_pdf_text(buf)
    lines = text.splitlines()
    rows = _parse_macro_blocks(lines)
    dates = [r.date for r in rows]
    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    warnings: list[str] = []
    if not rows:
        warnings.append(
            "No Macro-style blocks found (expected DD-MM-YY multiline movements). "
            "Try bank 'generic' or another bank code."
        )
    return ParseResult(
        rows=rows,
        warnings=warnings,
        bank_code=bank_code,
        file_type="pdf",
        period=period,
        currency="ARS",
    )
