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


__all__ = [
    "_slugify",
    "_hash",
    "_ensure_outdir",
    "_iso_or_none",
]
