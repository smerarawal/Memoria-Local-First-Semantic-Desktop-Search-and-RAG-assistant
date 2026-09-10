"""
DOCX text extraction using python-docx.

Strategy: extract paragraph text in order, treating each paragraph as a
logical unit. Page numbers are not available in DOCX files (page layout is
determined by the rendering engine, not the file format), so page_number is
always 1 for all content from a DOCX file.

This is a known limitation — DOCX files don't store page break positions in
a way that reliably maps to rendered pages. The citation will say "filename"
without a page number, which is honest rather than showing a wrong page number.
"""

from pathlib import Path
from typing import Optional


def extract_docx(path: Path) -> Optional[list[tuple[int, str]]]:
    """
    Extract text from a DOCX file as a single block (page_number=1).

    Returns:
        [(1, full_text)] — single-element list since page numbers aren't
        available from DOCX format.
        None if the file cannot be opened (corrupted / wrong format).
    """
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

    try:
        doc = Document(str(path))
    except Exception:
        return None

    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n\n".join(paragraphs)

    if not full_text.strip():
        return [(1, "")]

    return [(1, full_text)]
