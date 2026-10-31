"""
PowerPoint (.pptx) text extraction using built-in zipfile and XML parser.
Zero external dependencies required.
Extracts slide-by-slide text with page numbers mapping to slide numbers.
"""

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def extract_pptx(path: Path) -> Optional[list[tuple[int, str]]]:
    """
    Extract text from a .pptx presentation file.
    Returns list of (slide_number, text) tuples.
    """
    try:
        pages = []
        with zipfile.ZipFile(path, "r") as z:
            # Find all slide XML files
            slide_names = [
                n for n in z.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            ]

            def slide_num(name: str) -> int:
                m = re.search(r"slide(\d+)\.xml", name)
                return int(m.group(1)) if m else 999999

            slide_names.sort(key=slide_num)

            for idx, slide_file in enumerate(slide_names, start=1):
                try:
                    content = z.read(slide_file)
                    tree = ET.fromstring(content)
                    texts = [
                        node.text.strip()
                        for node in tree.iter()
                        if node.tag.endswith("}t") and node.text and node.text.strip()
                    ]
                    if texts:
                        slide_text = " ".join(texts)
                        pages.append((idx, slide_text))
                except Exception as slide_err:
                    logger.debug("Failed parsing %s in %s: %s", slide_file, path.name, slide_err)

        if not pages:
            clean_name = path.stem.replace("_", " ").replace("-", " ")
            pages.append((1, f"PowerPoint presentation: {path.name}. Title: {clean_name}"))

        logger.info("[pptx] Extracted %d slides from %s", len(pages), path.name)
        return pages

    except Exception as exc:
        logger.error("[pptx] Error extracting %s: %s", path.name, exc)
        return None
