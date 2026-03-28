from io import BytesIO

import fitz


def extract_pdf_text(buf: BytesIO) -> str:
    raw = buf.read()
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text() or "")
        return "\n".join(parts)
    finally:
        doc.close()
