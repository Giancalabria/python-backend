"""Mercado Pago account statement CSV (semicolon-separated, Argentine number format)."""

from __future__ import annotations

import csv
import io
from io import BytesIO

from app.parsers import register
from app.parsers.mercadopago_common import mp_date_to_iso, parse_argentine_amount
from app.schemas import ParseResult, ParseRow

_TRANSACTION_HEADER = "RELEASE_DATE"
_ENCODINGS = ("utf-8-sig", "utf-8", "latin-1", "cp1252")


def _clean(s: str) -> str:
    """Strip BOM remnants, non-breaking spaces, zero-width chars."""
    return s.replace("\ufeff", "").replace("\u00a0", " ").replace("\u200b", "").strip()


def _decode_and_parse(raw: bytes) -> tuple[list[list[str]], str]:
    """Try several encodings; return (rows, encoding_used) for the first one
    that successfully finds the RELEASE_DATE header."""
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
        reader = csv.reader(io.StringIO(text), delimiter=";")
        rows = list(reader)
        for row in rows:
            if row and _clean(row[0]).upper() == _TRANSACTION_HEADER:
                return rows, enc
    # Fallback: latin-1 never fails, return whatever we get
    text = raw.decode("latin-1")
    return list(csv.reader(io.StringIO(text), delimiter=";")), "latin-1"


@register("mercadopago", "csv")
def parse_mercadopago_csv(buf: BytesIO, bank_code: str) -> ParseResult:
    warnings: list[str] = []
    rows_out: list[ParseRow] = []
    dates: list[str] = []

    raw_bytes = buf.read()
    data_rows, enc_used = _decode_and_parse(raw_bytes)
    if enc_used != "utf-8-sig":
        warnings.append(f"Archivo decodificado con {enc_used} (no UTF-8).")

    # Find transaction table: header row starting with RELEASE_DATE
    start_idx = None
    col_date = col_desc = col_amt = None
    for i, row in enumerate(data_rows):
        if not row or not _clean(row[0] or ""):
            continue
        if _clean(row[0] or "").upper() == _TRANSACTION_HEADER:
            hdr = [_clean(c or "").upper() for c in row]
            try:
                col_date = hdr.index("RELEASE_DATE")
                col_desc = hdr.index("TRANSACTION_TYPE")
                col_amt = hdr.index("TRANSACTION_NET_AMOUNT")
            except ValueError:
                warnings.append("Unexpected Mercado Pago CSV headers; columns not found.")
                return ParseResult(
                    rows=[],
                    warnings=warnings,
                    bank_code=bank_code,
                    file_type="csv",
                    currency="ARS",
                )
            start_idx = i + 1
            break

    if start_idx is None:
        warnings.append("Not a Mercado Pago CSV: missing RELEASE_DATE header row.")
        return ParseResult(
            rows=[],
            warnings=warnings,
            bank_code=bank_code,
            file_type="csv",
            currency="ARS",
        )

    for row in data_rows[start_idx:]:
        if not row or all(not (c or "").strip() for c in row):
            continue
        if col_date >= len(row) or col_amt >= len(row):
            continue
        d_raw = (row[col_date] or "").strip()
        d = mp_date_to_iso(d_raw)
        if d is None:
            continue
        net = parse_argentine_amount(row[col_amt] if col_amt < len(row) else None)
        if net is None:
            continue
        # Expense rows only (debits); skip credits / rendimientos
        if net >= 0:
            continue
        desc = (row[col_desc] or "").strip() if col_desc is not None and col_desc < len(row) else ""
        ref_id_idx = col_desc + 1 if col_desc is not None else None
        ref_val = ""
        if ref_id_idx is not None and ref_id_idx < len(row):
            ref_val = (row[ref_id_idx] or "").strip()
        rows_out.append(
            ParseRow(
                date=d,
                description=desc.strip(),
                amount=abs(net),
                currency="ARS",
                raw={"reference_id": ref_val, "source": "mercadopago_csv"},
            )
        )
        dates.append(d)

    if not rows_out:
        warnings.append("No expense rows (negative amounts) found in CSV.")

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    return ParseResult(
        rows=rows_out,
        warnings=warnings,
        bank_code=bank_code,
        file_type="csv",
        currency="ARS",
        period=period,
    )
