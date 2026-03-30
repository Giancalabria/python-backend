"""Mercado Pago account statement CSV (semicolon-separated, Argentine number format)."""

from __future__ import annotations

import csv
from io import BytesIO, TextIOWrapper

from app.parsers import register
from app.parsers.mercadopago_common import mp_date_to_iso, parse_argentine_amount
from app.schemas import ParseResult, ParseRow

_TRANSACTION_HEADER = "RELEASE_DATE"


@register("mercadopago", "csv")
def parse_mercadopago_csv(buf: BytesIO, bank_code: str) -> ParseResult:
    warnings: list[str] = []
    rows_out: list[ParseRow] = []
    dates: list[str] = []

    text = TextIOWrapper(buf, encoding="utf-8-sig", newline="")
    reader = csv.reader(text, delimiter=";")
    data_rows = list(reader)

    # Find transaction table: header row starting with RELEASE_DATE
    start_idx = None
    col_date = col_desc = col_amt = None
    for i, row in enumerate(data_rows):
        if not row or not (row[0] or "").strip():
            continue
        if (row[0] or "").strip().upper() == _TRANSACTION_HEADER:
            hdr = [(c or "").strip().upper() for c in row]
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
