import csv
import re
from datetime import datetime
from io import BytesIO, TextIOWrapper

from app.parsers import register
from app.schemas import ParseResult, ParseRow

_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),
    re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"),
]


def _parse_date(cell: str) -> str | None:
    s = (cell or "").strip()
    if not s:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            if len(m.groups()) == 3 and len(m.group(1)) == 4:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            d, mo, y = m.group(1), m.group(2), m.group(3)
            return f"{y}-{mo}-{d}"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        return None


def _parse_amount(cell: str) -> float | None:
    if cell is None:
        return None
    s = str(cell).strip().replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s == "-" or s == ".":
        return None
    try:
        return float(s)
    except ValueError:
        return None


@register("generic", "csv")
def parse_generic_csv(buf: BytesIO, bank_code: str) -> ParseResult:
    warnings: list[str] = []
    rows: list[ParseRow] = []
    text = TextIOWrapper(buf, encoding="utf-8-sig", newline="")
    reader = csv.reader(text)
    header = next(reader, None)
    if not header:
        return ParseResult(
            rows=[],
            warnings=["Empty CSV"],
            bank_code=bank_code,
            file_type="csv",
        )

    lower = [h.strip().lower() for h in header]
    date_idx = next((i for i, h in enumerate(lower) if h in ("date", "fecha", "fecha valor")), None)
    desc_idx = next((i for i, h in enumerate(lower) if h in ("description", "descripcion", "detalle", "concepto")), None)
    amt_idx = next(
        (i for i, h in enumerate(lower) if h in ("amount", "importe", "monto", "debit", "credit")),
        None,
    )

    if date_idx is None or amt_idx is None:
        # Heuristic: first col date, second description, third amount
        if len(header) >= 3:
            date_idx, desc_idx, amt_idx = 0, 1, 2
            warnings.append("No header match; assumed columns: date, description, amount")
        else:
            return ParseResult(
                rows=[],
                warnings=["Could not detect columns; need date + amount columns or 3+ columns"],
                bank_code=bank_code,
                file_type="csv",
            )

    dates: list[str] = []
    for line in reader:
        if not line or all(not (c or "").strip() for c in line):
            continue
        if date_idx >= len(line) or amt_idx >= len(line):
            continue
        d = _parse_date(line[date_idx])
        amt = _parse_amount(line[amt_idx])
        if d is None or amt is None:
            continue
        desc = line[desc_idx].strip() if desc_idx is not None and desc_idx < len(line) else ""
        rows.append(ParseRow(date=d, description=desc, amount=abs(amt), raw={"line": line}))
        dates.append(d)

    period = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}
    return ParseResult(
        rows=rows,
        warnings=warnings,
        bank_code=bank_code,
        file_type="csv",
        period=period,
    )
