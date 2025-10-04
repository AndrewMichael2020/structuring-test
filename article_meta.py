"""article_meta.py

Lightweight metadata extraction (author, publication date) directly from raw
HTML before readability/text flattening removes structural cues.

Functions here are pure and resilient: they catch exceptions and return None
instead of raising.
"""

from __future__ import annotations

import json
import re
from typing import Optional, Tuple
from bs4 import BeautifulSoup  # type: ignore

from accident_utils import _iso_or_none


META_AUTHOR_KEYS = [
    'author', 'article:author', 'og:author', 'dc.creator', 'dc:creator',
]
META_DATE_KEYS = [
    'article:published_time', 'article:modified_time', 'og:updated_time',
    'pubdate', 'publish_date', 'date', 'dc.date', 'dc.date.issued',
]


def _first_non_empty(values):
    for v in values:
        if v:
            vt = v.strip()
            if vt:
                return vt
    return None


def extract_meta_from_html(html: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (author, publication_date_iso) best-effort.

    Strategy order:
    1. JSON-LD objects with @type Article/NewsArticle: author.name, datePublished
    2. <meta> tags (names/properties in known sets)
    3. <time> elements with datetime attribute or inner text
    4. Heuristic byline text nodes near top: lines starting with By/— By
    """
    if not html:
        return None, None
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return None, None

    author = None
    pub_date = None

    # helper: date-only normalization
    def _date_only(s: str | None):
        if not s:
            return None
        s = s.strip()
        iso = _iso_or_none(s)
        if iso and len(iso) == 10:
            return iso
        # Extract leading YYYY-MM-DD if present in datetime
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T\s]", s)
        if m:
            iso2 = _iso_or_none(m.group(1))
            if iso2:
                return iso2
        return iso if iso else None

    # 1. JSON-LD scanning
    try:
        for script in soup.find_all('script', type=lambda v: v and 'ld+json' in v.lower()):
            try:
                data = json.loads(script.string or '{}')
            except Exception:
                continue
            candidates = []
            if isinstance(data, list):
                candidates = data
            else:
                candidates = [data]
            for obj in candidates:
                if not isinstance(obj, dict):
                    continue
                t = obj.get('@type') or obj.get('@TYPE')
                if isinstance(t, list):
                    t = ','.join(t)
                if not t:
                    continue
                if any(x in str(t).lower() for x in ['article', 'newsarticle', 'report']):
                    # author can be dict, list, or string
                    a = obj.get('author')
                    if a and not author:
                        if isinstance(a, dict):
                            author = a.get('name') or a.get('@name')
                        elif isinstance(a, list):
                            # join multiple
                            names = []
                            for it in a:
                                if isinstance(it, dict) and it.get('name'):
                                    names.append(it['name'])
                                elif isinstance(it, str):
                                    names.append(it)
                            if names:
                                author = ', '.join(names)
                        elif isinstance(a, str):
                            author = a
                    dp = obj.get('datePublished') or obj.get('dateCreated')
                    if dp and not pub_date:
                        pub_date = _date_only(str(dp)) or pub_date
    except Exception:
        pass

    # 2. Meta tags
    try:
        if not author or not pub_date:
            for meta in soup.find_all('meta'):
                name = (meta.get('name') or meta.get('property') or '').lower()
                if not name:
                    continue
                content = meta.get('content') or ''
                if not author and name in META_AUTHOR_KEYS:
                    author = content.strip() or author
                if not pub_date and name in META_DATE_KEYS:
                    cand = _date_only(content)
                    if cand:
                        pub_date = cand
                if author and pub_date:
                    break
    except Exception:
        pass

    # 3. <time>
    try:
        if not pub_date:
            t = soup.find('time')
            if t:
                dt_attr = t.get('datetime') or t.get('content') or ''
                cand = _date_only(dt_attr) or _date_only(t.get_text(' ', strip=True))
                if cand:
                    pub_date = cand
    except Exception:
        pass

    # 4. Byline heuristic (only if author still missing)
    if not author:
        try:
            visible = ' '.join(soup.stripped_strings)
            head = visible[:1200]
            m = re.search(r"(?:^|[\n\-–|•])\s*(?:By|BY)\s+([A-Z][A-Za-z\-']+(?:\s+[A-Z][A-Za-z\-']+){0,4})", head)
            if m:
                author = m.group(1).strip()
        except Exception:
            pass

    return author, pub_date


__all__ = [
    'extract_meta_from_html',
]
