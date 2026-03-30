"""Shared helpers for Mercado Pago statement exports (CSV / XLSX / PDF)."""

from __future__ import annotations

import re

_MP_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def mp_date_to_iso(s: str) -> str | None:
    s = (s or "").strip()
    m = _MP_DATE.match(s)
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    return f"{y}-{mo}-{d}"


def parse_argentine_amount(cell: str | int | float | None) -> float | None:
    """Parse amounts like -30.000,00 or 514,40 (dot thousands, comma decimal)."""
    if cell is None:
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return float(cell)
    s = str(cell).strip()
    if not s:
        return None
    s = s.replace("$", "").strip()
    s = s.replace("\u00a0", "").strip()
    if not s or s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None
