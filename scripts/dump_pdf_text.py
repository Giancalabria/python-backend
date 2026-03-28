"""One-off: dump PDF text for parser development. Run from repo root or parser-api."""
import os
import sys

import fitz

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PDFS = [
    "ComprobanteBP - 2026-03-27-135153 - 2026-03-27-135155.pdf",
    "Resumen - Marzo 2026.pdf",
    "Resumen de tarjeta de cre'dito VISA-06-04-2026.pdf",
]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    for name in PDFS:
        path = os.path.join(ROOT, name)
        print("=" * 80)
        print("FILE:", name)
        print("=" * 80)
        if not os.path.isfile(path):
            print("MISSING:", path)
            continue
        doc = fitz.open(path)
        text = ""
        for p in doc:
            text += p.get_text() or ""
        doc.close()
        lines = [l.rstrip() for l in text.splitlines()]
        for i, L in enumerate(lines[:n]):
            print(f"{i:3}|{L}")
        print("... total lines", len(lines))


if __name__ == "__main__":
    main()
