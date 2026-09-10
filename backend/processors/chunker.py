"""
Text chunker — splits extracted page text into overlapping chunks.

Why chunking matters:
  Embedding a 30-page PDF as a single vector is wrong for two reasons:
  1. The model has a max sequence length (~256 tokens for MiniLM). Long text
     gets truncated, silently losing most content.
  2. A query about "pooling in CNNs" shouldn't match an entire PDF — it should
     match the specific paragraph that explains pooling. Chunk-level retrieval
     is more precise.

Strategy: sliding window over characters.
  CHUNK_SIZE  = 1000 characters  (~200-250 tokens, well within MiniLM's 256 limit)
  CHUNK_OVERLAP = 100 characters  (prevents breaking sentences mid-thought at boundaries)

Why character-based rather than token-based:
  Tokenizer is model-specific and adds a dependency just for chunking.
  At 4 chars/token average, 1000 chars ≈ 250 tokens — safe margin below 256.
  For a document retrieval use-case the granularity difference is negligible.

Returns:
  List of (chunk_index, page_number, chunk_text) tuples.
  chunk_index is 0-based within the document (not per-page).
  page_number is the source page the chunk text came from.
"""

CHUNK_SIZE = 1000     # characters
CHUNK_OVERLAP = 100   # characters of overlap between consecutive chunks


def chunk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    """
    Take the [(page_num, text)] output from a processor and produce
    [(chunk_index, page_num, chunk_text)] ready for embedding.

    Each page is chunked independently — we never merge text across page
    boundaries. This preserves page-level attribution: a chunk on page 7
    stays associated with page 7 in citations.

    Empty chunks (after stripping) are skipped.
    """
    chunks: list[tuple[int, int, str]] = []
    chunk_index = 0

    for page_num, text in pages:
        text = text.strip()
        if not text:
            continue

        start = 0
        while start < len(text):
            end = start + CHUNK_SIZE
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append((chunk_index, page_num, chunk_text))
                chunk_index += 1

            if end >= len(text):
                break  # Reached end of this page's text

            # Advance window, stepping back by OVERLAP so chunks share context
            start = end - CHUNK_OVERLAP

    return chunks
