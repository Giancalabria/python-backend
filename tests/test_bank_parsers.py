"""Regression tests for bank PDF parsers. Skips if sample PDFs are not present (e.g. gitignored)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MP_EXAMPLES = REPO_ROOT / "frontend" / "examples"
MP_CSV = MP_EXAMPLES / "account_statement_931f5bdb-f444-4f51-a0d6-d9061ded3345-3.csv"
MP_XLSX = MP_EXAMPLES / "account_statement_931f5bdb-f444-4f51-a0d6-d9061ded3345.xlsx"
MP_PDF = MP_EXAMPLES / "downloadMobile_260330131410.pdf"


def _first_pdf(glob_pat: str) -> Path | None:
    found = list(REPO_ROOT.glob(glob_pat))
    return found[0] if found else None


@pytest.fixture(scope="module")
def santander_pdf() -> Path | None:
    return _first_pdf("*VISA*.pdf")


@pytest.fixture(scope="module")
def macro_pdf() -> Path | None:
    p = REPO_ROOT / "Resumen - Marzo 2026.pdf"
    return p if p.is_file() else None


@pytest.fixture(scope="module")
def patagonia_pdf() -> Path | None:
    found = list(REPO_ROOT.glob("ComprobanteBP*.pdf"))
    return found[0] if found else None


def test_santander_visa_dates_and_row_count(santander_pdf: Path | None) -> None:
    if santander_pdf is None:
        pytest.skip("No *VISA*.pdf in repo root (sample not present)")
    from app.parsers.bank_santander_pdf import parse_santander_pdf

    r = parse_santander_pdf(BytesIO(santander_pdf.read_bytes()), "santander")

    ars_rows = [row for row in r.rows if row.currency is None]
    usd_rows = [row for row in r.rows if row.currency == "USD"]

    # ARS rows: previously 10, still 10 (unchanged)
    assert len(ars_rows) == 10, f"Expected 10 ARS rows, got {len(ars_rows)}"

    # USD rows: previously skipped, now emitted
    assert len(usd_rows) >= 1, "Expected at least one USD row (e.g. APPLE, GOOGLE, ASANAREBEL)"

    # Spot-check ARS row dates
    by_desc = {row.description.split()[0]: row for row in ars_rows}
    assert by_desc["006328"].date == "2025-10-15"
    assert by_desc["100183"].date == "2025-11-29"
    assert any("CLUB ATLETICO" in row.description and row.date == "2026-02-22" for row in ars_rows)

    # Spot-check USD rows exist for known services
    usd_descriptions = " ".join(row.description.upper() for row in usd_rows)
    assert "APPLE" in usd_descriptions or "GOOGLE" in usd_descriptions or "ASANAREBEL" in usd_descriptions

    # All USD rows must have positive amounts and valid dates
    for row in usd_rows:
        assert row.amount > 0, f"USD row has non-positive amount: {row}"
        assert len(row.date) == 10 and row.date[4] == "-", f"Bad date in USD row: {row}"

    # No USD amounts should leak into ARS rows
    for row in ars_rows:
        assert row.currency is None, f"ARS row has unexpected currency: {row}"


def test_macro_marzo_parser(macro_pdf: Path | None) -> None:
    if macro_pdf is None:
        pytest.skip("Resumen - Marzo 2026.pdf not in repo root")
    from app.parsers.bank_macro_pdf import parse_macro_pdf

    r = parse_macro_pdf(BytesIO(macro_pdf.read_bytes()), "macro")
    assert len(r.rows) >= 1
    # All rows should have currency=None (ARS) or "USD"
    for row in r.rows:
        assert row.currency in (None, "USD"), f"Unexpected currency on row: {row}"


def test_patagonia_parser(patagonia_pdf: Path | None) -> None:
    if patagonia_pdf is None:
        pytest.skip("No ComprobanteBP*.pdf in repo root")
    from app.parsers.bank_patagonia_pdf import parse_patagonia_pdf

    r = parse_patagonia_pdf(BytesIO(patagonia_pdf.read_bytes()), "patagonia")
    assert len(r.rows) >= 1
    for row in r.rows:
        assert row.currency in (None, "USD"), f"Unexpected currency on row: {row}"


def test_mercadopago_csv_xlsx_pdf_same_expense_rows() -> None:
    """Commit Mercado Pago exports in frontend/examples: CSV, XLSX, PDF share one dataset."""
    if not MP_CSV.is_file() or not MP_XLSX.is_file() or not MP_PDF.is_file():
        pytest.skip("Mercado Pago example files missing under frontend/examples")

    from app.parsers.mercadopago_csv import parse_mercadopago_csv
    from app.parsers.mercadopago_pdf import parse_mercadopago_pdf
    from app.parsers.mercadopago_xlsx import parse_mercadopago_xlsx

    c = parse_mercadopago_csv(BytesIO(MP_CSV.read_bytes()), "mercadopago")
    x = parse_mercadopago_xlsx(BytesIO(MP_XLSX.read_bytes()), "mercadopago")
    p = parse_mercadopago_pdf(BytesIO(MP_PDF.read_bytes()), "mercadopago")

    assert len(c.rows) == 38
    assert len(x.rows) == len(c.rows)
    assert len(p.rows) == len(c.rows)

    total = round(sum(r.amount for r in c.rows), 2)
    assert total == 666_593.51
    assert round(sum(r.amount for r in x.rows), 2) == total
    assert round(sum(r.amount for r in p.rows), 2) == total

    def sig(rows):
        return {(r.date, r.raw.get("reference_id"), round(r.amount, 2)) for r in rows}

    assert sig(c.rows) == sig(p.rows)

    transfer_row = next(r for r in c.rows if "Salvay" in r.description)
    assert transfer_row.date == "2026-02-02"
    assert transfer_row.amount == 30_000.00
    assert transfer_row.raw.get("reference_id") == "144494680302"
