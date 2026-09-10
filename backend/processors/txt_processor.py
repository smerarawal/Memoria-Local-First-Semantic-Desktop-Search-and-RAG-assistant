"""
Plain text and Markdown extraction.

Both TXT and MD files are read as-is. Markdown-specific syntax (headers,
bold, links) is left in place — the embedding model handles natural text
including lightweight markup without needing a Markdown parser first.
If we later add a UI markdown renderer for previews, we can strip syntax
then, but for embedding purposes it doesn't hurt.

Encoding: try UTF-8 first, fall back to latin-1. Files that fail both
return None so the caller marks them as 'failed'.
"""

from pathlib import Path
from typing import Optional


def extract_text(path: Path) -> Optional[list[tuple[int, str]]]:
    """
    Read a .txt or .md file and return its content as [(1, text)].

    Returns:
        [(1, content)] on success.
        None if the file cannot be decoded.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            return [(1, text.strip())]
        except UnicodeDecodeError:
            continue
        except OSError:
            return None

    return None  # Both encodings failed — binary file with wrong extension
