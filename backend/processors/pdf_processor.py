"""
PDF text extraction using PyMuPDF (fitz).

Why PyMuPDF over pdfplumber/pypdf:
  - Fastest pure-Python PDF library for text extraction
  - Preserves page numbers cleanly (critical for citations in RAG)
  - Handles multi-column layouts better than most alternatives
  - Returns structured page data, not a single flat string

Returns a list of (page_number, text) tuples — the page number is stored
in the chunks table so RAG can cite exact pages, matching the spec requirement
of "CNN_Notes.pdf — Page 7" style citations.

Password-protected PDFs: fitz raises an exception that we surface as None
so the calling service can mark the file as 'failed' rather than crashing.
"""

from pathlib import Path
from typing import Optional


def extract_pdf(path: Path) -> Optional[list[tuple[int, str]]]:
    """
    Extract text from a PDF, page by page.

    Returns:
        List of (1-indexed page number, page text) tuples.
        None if the file cannot be opened (password-protected, corrupted).
        Pages with no extractable text are still included with empty string
        so page numbering stays intact — important for citation accuracy.
    """
    try:
        import fitz  # PyMuPDF — imported here so the rest of the app
                     # still boots if PyMuPDF isn't installed yet.
    except ImportError:
        raise RuntimeError("PyMuPDF is not installed. Run: pip install pymupdf")

    try:
        doc = fitz.open(str(path))
    except Exception:
        return None  # Corrupted or password-protected

    if doc.needs_pass:
        doc.close()
        return None  # Password-protected — can't extract without the key

    pages: list[tuple[int, str]] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")  # "text" mode: plain text, preserves layout
        pages.append((i, text.strip()))

    doc.close()
    return pages
