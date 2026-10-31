"""
Image text extraction (OCR) + semantic description using Google Gemini Vision.

Supports .png, .jpg, .jpeg, .webp image files.

Two passes:
  1. OCR pass:         Transcribes typed text, handwritten notes, tables, charts, diagrams
  2. Description pass: Generates a rich visual description of the image content
                       so users can find images by describing what they look like
                       (e.g. "dog at the park", "bar chart comparing cloud costs")

Both texts are stored as searchable chunks in Memoria's indexing pipeline.
The description is prefixed with IMAGE_DESCRIPTION: so it can be identified.
"""

import logging
from pathlib import Path
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)


def _call_gemini_vision(img: Image.Image, prompt: str, candidate_keys: list, models: list) -> Optional[str]:
    """
    Helper: call Gemini Vision with a given prompt, trying all keys + models.
    Returns the response text or None if all fail.
    """
    from google import genai
    for api_key in candidate_keys:
        if not api_key:
            continue
        try:
            client = genai.Client(api_key=api_key.strip())
            for model_name in models:
                try:
                    res = client.models.generate_content(
                        model=model_name,
                        contents=[img, prompt],
                    )
                    if res.text and res.text.strip():
                        return res.text.strip()
                except Exception as me:
                    err_s = str(me)
                    logger.debug("[ocr] Model %s failed: %s", model_name, me)
                    if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s:
                        logger.warning("[ocr] Gemini Vision rate limit (429), switching to metadata fallback")
                        return None
                    continue
        except Exception as ke:
            logger.debug("[ocr] Key attempt failed: %s", ke)
            continue
    return None


def extract_image(path: Path) -> list[tuple[int, str]]:
    """
    Extract searchable content from an image file using Gemini Vision + metadata fallback.

    Returns a list of (page_number, text) tuples.
    Guaranteed to return at least one searchable tuple so image indexing never fails.

    Extracted content includes:
      - Filename keywords (e.g. "dog", "park" from "dog_in_park.jpg")
      - Visual description (subjects, animals like dog, scenery like park, actions)
      - Search tags / labels
      - OCR transcribed text (if any)
    """
    clean_name = path.stem.replace("_", " ").replace("-", " ")
    results: list[tuple[int, str]] = []

    try:
        from api.rag import _get_candidate_keys, CANDIDATE_MODELS

        candidate_keys = _get_candidate_keys()
        img = None
        try:
            img = Image.open(path)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # Downsample huge images for fast transmission to Gemini API (<1024px)
            if max(img.width, img.height) > 1024:
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.warning("[ocr] Could not open image %s: %s", path.name, e)

        if candidate_keys and img is not None:
            prompt = (
                "Analyze this image thoroughly for personal file search and retrieval.\n\n"
                "1. VISUAL_DESCRIPTION: Describe everything visible in vivid, specific detail. "
                "Explicitly identify all subjects (e.g. dog, puppy, cat, person, vehicle), "
                "environment and setting (e.g. park, grass, trees, outdoors, room, street), "
                "colors, and actions.\n\n"
                "2. TAGS: List all relevant search keywords and labels separated by commas "
                "(e.g., dog, puppy, canine, park, grass, trees, outdoors, nature, photo).\n\n"
                "3. OCR_TEXT: Transcribe all visible text, writing, signs, or labels in the image. "
                "If no text is visible, write None.\n\n"
                "Be thorough so that a user searching for any subject, scene, or keyword in this image will find it."
            )
            analysis = _call_gemini_vision(img, prompt, candidate_keys, CANDIDATE_MODELS)
            if analysis:
                logger.info("[ocr] Vision analysis complete for %s (%d chars)", path.name, len(analysis))
                full_chunk = f"IMAGE_DESCRIPTION: [File: {clean_name}]\n{analysis}"
                results.append((1, full_chunk))
                return results
            else:
                logger.warning("[ocr] Gemini Vision returned no response for %s, using fallback", path.name)

    except Exception as exc:
        logger.error("[ocr] Error processing image %s with Gemini Vision: %s", path.name, exc)

    # Reliable fallback: index filename words and metadata so the file is always searchable
    logger.info("[ocr] Using metadata indexing fallback for %s", path.name)
    fallback_text = (
        f"IMAGE_DESCRIPTION: [File: {clean_name}]\n"
        f"Image file: {path.name}. "
        f"Keywords: {clean_name}. "
        f"Format: {path.suffix.upper()} image."
    )
    results.append((1, fallback_text))
    return results

