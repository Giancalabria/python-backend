"""Regression tests for bank PDF parsers. Skips if sample PDFs are not present (e.g. gitignored)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert len(r.rows) == 10
    by_desc = {row.description.split()[0]: row for row in r.rows}
    assert by_desc["006328"].date == "2025-10-15"
    assert by_desc["100183"].date == "2025-11-29"
    assert any("CLUB ATLETICO" in row.description and row.date == "2026-02-22" for row in r.rows)
    assert not any("APPLE" in row.description or "USD" in row.description.upper() for row in r.rows)


def test_macro_marzo_parser(macro_pdf: Path | None) -> None:
    if macro_pdf is None:
        pytest.skip("Resumen - Marzo 2026.pdf not in repo root")
    from app.parsers.bank_macro_pdf import parse_macro_pdf

    r = parse_macro_pdf(BytesIO(macro_pdf.read_bytes()), "macro")
    assert len(r.rows) >= 1


def test_patagonia_parser(patagonia_pdf: Path | None) -> None:
    if patagonia_pdf is None:
        pytest.skip("No ComprobanteBP*.pdf in repo root")
    from app.parsers.bank_patagonia_pdf import parse_patagonia_pdf

    r = parse_patagonia_pdf(BytesIO(patagonia_pdf.read_bytes()), "patagonia")
    assert len(r.rows) >= 1
