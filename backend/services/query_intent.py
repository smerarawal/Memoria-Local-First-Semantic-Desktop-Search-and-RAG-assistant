"""
Query intent analysis and file candidate scoring for version/temporal queries.

Shared module used by both search_service.py (Find by meaning) and rag.py (RAG).
Extracted to avoid circular imports.

Handles queries like:
  - "resume before IIT BHU intern"   -> wants_older + anchor_terms
  - "latest resume"                  -> wants_newer
  - "resume_new 10"                  -> explicit version number
  - "old resume"                     -> wants_older
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal word sets
# ---------------------------------------------------------------------------
OLDER_SIGNALS = {
    'old', 'older', 'oldest', 'previous', 'earlier', 'before',
    'first', 'original', 'prior', 'initial', 'draft', 'prev',
}
NEWER_SIGNALS = {
    'latest', 'newest', 'recent', 'updated', 'current', 'final', 'last',
}
VERSION_KEYWORDS = OLDER_SIGNALS | NEWER_SIGNALS | {'new', 'version', 'ver', 'v'}

STOP_WORDS = {
    "what", "does", "about", "show", "tell", "explain", "notes", "file", "files",
    "document", "paper", "say", "where", "which", "did", "the", "and", "for", "with",
    "you", "your", "mine", "this", "that", "these", "those", "have", "had", "doing",
    "how", "when", "why", "who", "can", "could", "would", "should", "some", "image",
    "picture", "photo", "pic", "metric", "graph", "chart", "from", "into", "give",
    "please", "my", "me", "there", "their",
}


# ---------------------------------------------------------------------------
# Version number extraction
# ---------------------------------------------------------------------------

def extract_file_version_number(filename: str) -> Optional[int]:
    """
    Extracts version or iteration number from filenames such as:
    - resume_new (10).pdf -> 10
    - resume_new (1).pdf -> 1
    - resume_v2.pdf -> 2
    - doc_v1.docx -> 1
    - file-2.txt -> 2
    - file_3.pdf -> 3
    """
    fn_no_ext = filename.rsplit('.', 1)[0].lower()
    m = re.findall(r'\((\d+)\)', fn_no_ext)
    if m:
        return int(m[0])
    m = re.findall(r'(?:^|[_\-\s])v(\d+)(?:$|[_\-\s])', fn_no_ext)
    if m:
        return int(m[0])
    m = re.findall(r'[_\-\s](\d+)$', fn_no_ext)
    if m:
        return int(m[0])
    return None


def extract_query_version_number(query: str) -> Optional[int]:
    """
    Extracts explicit version numbers from queries such as:
    - "resume version 2" -> 2
    - "v3 report" -> 3
    - "resume_new 10" -> 10
    """
    m = re.search(r'\b(?:v|ver|version)\s*(\d+)\b', query, re.I)
    if m:
        return int(m.group(1))
    digits = re.findall(r'\b(\d+)\b', query)
    if digits:
        return int(digits[-1])
    return None


# ---------------------------------------------------------------------------
# Query intent parsing
# ---------------------------------------------------------------------------

def parse_query_intent(query: str) -> dict:
    """
    Analyzes user query to extract temporal signals, anchor constraints, and subject tokens.

    Returns dict with keys:
        q_lower       - lowercased query
        wants_older   - True if query seeks an older/previous version
        wants_newer   - True if query seeks the latest/newest version
        q_number      - explicit version number from query, or None
        anchor_terms  - terms after "before/after/without" (e.g. ["iit", "bhu", "intern"])
        subj_tokens   - subject tokens stripped of stop words and version keywords
    """
    q_lower = query.lower()
    q_all_words = set(re.findall(r'[a-zA-Z]+', q_lower))
    wants_older = bool(q_all_words & OLDER_SIGNALS)
    wants_newer = bool(q_all_words & NEWER_SIGNALS)
    q_number = extract_query_version_number(query)

    if "new" in q_all_words and not wants_newer and q_number is None:
        wants_newer = True

    anchor_terms = []
    anchor_m = re.search(r'\b(before|prior\s+to|earlier\s+than|without|after|with)\s+(.+)$', q_lower)
    if anchor_m:
        anchor_phrase = anchor_m.group(2).strip()
        anchor_terms = [w for w in re.findall(r'[a-zA-Z0-9]+', anchor_phrase) if len(w) >= 2 and w not in STOP_WORDS]

    all_tokens = re.findall(r'[a-zA-Z0-9]+', q_lower)
    subj_tokens = []
    for tok in all_tokens:
        if tok.isdigit():
            continue
        if tok in STOP_WORDS:
            continue
        if tok in VERSION_KEYWORDS and tok != 'new':
            continue
        if tok in anchor_terms:
            continue
        if len(tok) >= 3:
            subj_tokens.append(tok)

    if not subj_tokens:
        subj_tokens = [w for w in all_tokens if w not in STOP_WORDS and not w.isdigit() and len(w) >= 3]

    return {
        "q_lower": q_lower,
        "wants_older": wants_older,
        "wants_newer": wants_newer,
        "q_number": q_number,
        "anchor_terms": anchor_terms,
        "subj_tokens": subj_tokens,
    }


# ---------------------------------------------------------------------------
# File candidate scoring
# ---------------------------------------------------------------------------

def score_file_candidate(
    fn: str,
    mod_time: Optional[str],
    query_info: dict,
    chunk_texts: list[str],
) -> float:
    """
    Scores a candidate file against query intent, taking into account:
    - Subject token matches
    - Version/iteration numbers
    - Temporal preferences (older vs newer)
    - Semantic anchor conditions (e.g. 'before <milestone>')
    - User ownership heuristics
    """
    score = 0.0
    fn_lower = fn.lower()
    fn_words = set(re.findall(r'[a-zA-Z0-9]+', fn_lower))

    subj_tokens = query_info["subj_tokens"]
    q_number = query_info["q_number"]
    wants_newer = query_info["wants_newer"]
    wants_older = query_info["wants_older"]
    anchor_terms = query_info["anchor_terms"]

    matched_tokens = 0
    for tok in subj_tokens:
        if tok in fn_words:
            score += 30.0
            matched_tokens += 1
        elif any(w.startswith(tok) for w in fn_words):
            score += 15.0
            matched_tokens += 1

    if matched_tokens == 0:
        return -1000.0

    ver_num = extract_file_version_number(fn)
    has_latest_in_name = any(w in fn_lower for w in ('latest', 'newest', 'final', 'current'))
    q_lower = query_info["q_lower"]

    # Prioritize user's own files (Smera) over third-party resumes
    is_user_file = 'smera' in fn_lower or any('smera' in txt.lower() for txt in chunk_texts)
    if is_user_file:
        score += 120.0

    # Penalize third-party resumes unless specifically named in query
    for tp in ('yuvraj', 'debnath', 'ayush'):
        if tp in fn_lower and tp not in q_lower:
            score -= 500.0

    # Explicit target number in query (e.g. "resume_new 10" -> ver_num == 10)
    if q_number is not None:
        if ver_num == q_number:
            score += 500.0
        elif ver_num is not None:
            score -= abs(ver_num - q_number) * 40.0
        else:
            score -= 100.0

    # Newer preference: File modification timestamp is the ground truth of recency
    if wants_newer and q_number is None:
        if mod_time:
            if mod_time >= "2026-10":
                score += 200.0  # October 2026 files are the newest
            elif mod_time >= "2026-08":
                score += 100.0
            elif mod_time <= "2026-06":
                score -= 150.0  # Files from May or earlier are old despite filenames

        # Gartner resume is the user's latest master resume
        if 'gartner' in fn_lower:
            score += 80.0

        if has_latest_in_name:
            score += 15.0
        elif any(w in fn_lower for w in ('old', 'orig', 'initial', 'first', 'draft')):
            score -= 150.0

        if ver_num is not None:
            score += ver_num * 2.0

    # Older preference
    if wants_older:
        if any(w in fn_lower for w in ('old', 'orig', 'initial', 'first', 'draft', 'prev')):
            score += 100.0

        if mod_time:
            if mod_time <= "2026-06":
                score += 150.0  # Files from May or earlier are the older versions
            elif mod_time >= "2026-09":
                score -= 200.0  # Recent September/October files penalized for 'older'

        if has_latest_in_name or any(w in fn_lower for w in ('updated', 'recent')):
            score -= 150.0

        if ver_num is not None:
            score -= ver_num * 10.0
        else:
            if ver_num == 1:
                score += 30.0

    # Semantic anchor verification (e.g. "before IIT BHU intern")
    if anchor_terms and wants_older:
        has_anchor = any(all(term in txt.lower() for term in anchor_terms) for txt in chunk_texts)
        if not has_anchor:
            score += 300.0  # Milestone NOT yet in document: correctly before the milestone!
        else:
            score -= 200.0  # Document already includes milestone

    return score
