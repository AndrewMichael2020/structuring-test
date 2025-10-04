"""Shared helpers for accident extraction modules."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from time_utils import now_pst_filename_ts


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:10]


def _ensure_outdir(url: str, base_output: str = "artifacts") -> Path:
    domain = urlparse(url).netloc.replace("www.", "")
    try:
        ts = now_pst_filename_ts()
    except Exception:
        ts = now_pst_filename_ts()
    p = Path(base_output) / _slugify(domain) / ts
    p.mkdir(parents=True, exist_ok=True)
    return p


def _iso_or_none(s: str | None) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        datetime.fromisoformat(s)
        return s
    except Exception:
        pass
    # try dateutil for natural language formats if available
    try:
        from dateutil import parser as dateparser  # type: ignore
        try:
            dt = dateparser.parse(s, fuzzy=True)  # type: ignore
            if dt:
                return dt.date().isoformat()
        except Exception:
            pass
    except Exception:
        pass
    # Lightweight fallback parse: YYYY/MM/DD, MM/DD/YYYY
    for pat in (r"^(\d{4})/(\d{2})/(\d{2})$", r"^(\d{2})/(\d{2})/(\d{4})$"):
        m = re.match(pat, s)
        if m:
            try:
                if len(m.group(1)) == 4:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d).date().isoformat()
            except Exception:
                pass
    return None


# -------------------- lightweight article meta parsing --------------------

_AUTHOR_PATTERNS = [
    # Start-of-text simple byline
    re.compile(r"^(?:by|By)\s+([A-Z][A-Za-z\-']+(?:\s+[A-Z][A-Za-z\-']+){0,4})(?=\b|,)") ,
    # With preceding dash / pipe / bullet
    re.compile(r"(?:^|[\n\-–|•])\s*(?:by|By)\s+([A-Z][A-Za-z\-']+(?:\s+[A-Z][A-Za-z\-']+){0,4})(?=\b|[,|])") ,
    # Single token authors (e.g., 'By Staff')
    re.compile(r"(?:^|\n)\s*(?:by|By)\s+([A-Z][A-Za-z]{2,20})(?=\b|[,|])"),
]

_DATE_LABEL_PATTERN = re.compile(
    r"(?i)(published|posted|updated|last\s+updated|date|on)[:\s\-]{0,5}"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{1,2})(?:,)?(?:\s+\d{4})?"
    r"|\d{4}-\d{2}-\d{2}"  # ISO
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"  # numeric
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"  # 2 Oct 2024
    r")"
)


def parse_report_author(text: str) -> str | None:
    """Attempt to locate a reporter/author line.

    Strategy: Look only in the first ~500 characters to avoid capturing quoted
    'By <Person>' fragments later in the article body.
    """
    if not text:
        return None
    head = text[:500]
    for pat in _AUTHOR_PATTERNS:
        m = pat.search(head)
        if m:
            name = m.group(1).strip()
            # Basic sanity: avoid single generic tokens
            if name.lower() in {"ap", "reuters"}:
                continue
            return name
    return None


def parse_publication_date(text: str) -> str | None:
    """Extract a publication date string and normalize to ISO when possible.

    We search only the first 1200 characters; if none found, fall back to any
    ISO-like date anywhere. Uses _iso_or_none for normalization.
    """
    if not text:
        return None
    snippet = text[:1800]
    # labeled date patterns (Published:, Updated:, etc.)
    m = _DATE_LABEL_PATTERN.search(snippet)
    candidate = None
    if m:
        candidate = m.group(2).strip().rstrip(').,;')
    else:
        # fallback: first standalone Month DD, YYYY
        m2 = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
            snippet,
            flags=re.IGNORECASE,
        )
        if m2:
            candidate = m2.group(0)
    if not candidate:
        # final fallback: any ISO date anywhere in text
        m3 = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        if m3:
            candidate = m3.group(0)
    if candidate:
        iso = _iso_or_none(candidate)
        return iso
    return None


__all__ = [
    "_slugify",
    "_hash",
    "_ensure_outdir",
    "_iso_or_none",
    'parse_publication_date',
    'parse_report_author',
]
