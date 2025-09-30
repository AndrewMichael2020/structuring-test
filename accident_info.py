#!/usr/bin/env python3
"""
accident_info.py

Page-level accident metadata extraction using OpenAI gpt-4o-mini.

- Fetches page HTML and extracts main article text (robust selectors + fallback).
- Asks gpt-4o-mini to return STRICT JSON with only present fields.
- Validates and normalizes dates to ISO (YYYY-MM-DD) when possible.
- Writes artifacts/<domain>/<timestamp>/accident_info.json unless out_dir is provided.

Usage (standalone):
    python accident_info.py "<URL>"

Programmatic:
    from accident_info import extract_accident_info
    json_path = extract_accident_info(url, out_dir=<existing run folder>)

Env:
    OPENAI_API_KEY must be set.
"""

import os
import re
import json
import sys
import time
import hashlib
import requests
from urllib.parse import urlparse
from datetime import datetime
from bs4 import BeautifulSoup
from pathlib import Path

try:
    # optional date normalization helper
    from dateutil import parser as dateparser  # type: ignore
    _HAS_DATEUTIL = True
except Exception:
    _HAS_DATEUTIL = False

from openai import OpenAI
_client = OpenAI()

# -------------------- helpers --------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)

def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:10]

def _ensure_outdir(url: str, base_output: str = "artifacts") -> Path:
    domain = urlparse(url).netloc.replace("www.", "")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = Path(base_output) / _slugify(domain) / ts
    p.mkdir(parents=True, exist_ok=True)
    return p

def _iso_or_none(s: str | None) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    # accept already ISO
    try:
        datetime.fromisoformat(s)
        return s
    except Exception:
        pass
    # try to parse common natural dates if dateutil exists
    if _HAS_DATEUTIL:
        try:
            dt = dateparser.parse(s, fuzzy=True)  # type: ignore
            if dt:
                return dt.date().isoformat()
        except Exception:
            return None
    return None

def _clean_text_blocks(txt: str) -> str:
    # collapse whitespace, keep sentences
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()

def _extract_article_text(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (GitHub Codespaces; +metadata-extractor)"
    }
    html = requests.get(url, headers=headers, timeout=timeout).text
    soup = BeautifulSoup(html, "html.parser")

    # Prefer article containers
    candidates = []
    for sel in [
        "article",                # generic
        "div.entry-content",      # WP
        "div.post-content",       # common blogs
        "main",                   # generic
        "div#content", "div.content"
    ]:
        node = soup.select_one(sel)
        if node:
            candidates.append(node)

    node = candidates[0] if candidates else soup.body or soup
    # collect paragraphs and headings only (avoid nav/footers)
    blocks = []
    for el in node.find_all(["p", "h1", "h2", "h3", "li"]):
        t = el.get_text(" ", strip=True)
        if t and len(t) > 2:
            blocks.append(t)
    text = " ".join(blocks)
    return _clean_text_blocks(text)


# -------------------- LLM extraction --------------------

_PROMPT = """You extract accident meta-information from a news/story page about a mountain incident.

Rules:
- Consider ONLY the provided article text.
- If a field is not supported by the text, OMIT that key (do not output null).
- Return STRICT JSON, no prose, no markdown code fences.
- Use these keys (all optional, include only if confidently present):
  - "rescuers": array of strings (organizations like "Squamish Search and Rescue (SAR)", "Sea to Sky RCMP")
  - "area": string (primary feature/peak, e.g., "Atwell Peak")
  - "park": string (official park name, e.g., "Garibaldi Provincial Park")
  - "closest_municipality": string (e.g., "Whistler, BC")
  - "trailhead": string (official trailhead name)
  - "missing": boolean
  - "missing_since": string in ISO YYYY-MM-DD
  - "recovered": boolean
  - "recovery_date": string in ISO YYYY-MM-DD

Guidance:
- Prefer canonical organization names and expansions when present in text.
- Normalize dates to ISO with the correct year if it is stated in the article text; otherwise OMIT.
- Do not invent details; only include keys you are confident about.

Now extract from this ARTICLE TEXT:
"""

def _llm_extract(article_text: str) -> dict:
    # Truncate extremely long pages to keep costs down but keep most relevant content
    content = article_text[:18000]

    resp = _client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT + "\n" + content}
                ]
            }
        ],
    )
    raw = resp.choices[0].message.content.strip()

    # try parse JSON; if fails, try a repair pass
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # simple recovery attempt: ask for pure JSON only
    repair = _client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Convert the following to STRICT JSON only, no explanations:\n" + raw}
            ]
        }],
    )
    try:
        return json.loads(repair.choices[0].message.content.strip())
    except Exception:
        return {}


def _postprocess(obj: dict) -> dict:
    """Validate types and normalize dates; drop unknown keys and ill-typed values."""
    allowed = {
        "rescuers": list,
        "area": str,
        "park": str,
        "closest_municipality": str,
        "trailhead": str,
        "missing": bool,
        "missing_since": str,
        "recovered": bool,
        "recovery_date": str,
    }
    out: dict = {}
    for k, v in obj.items():
        if k not in allowed:
            continue
        typ = allowed[k]
        if typ is list and isinstance(v, list):
            # keep unique, non-empty strings
            vals = [s.strip() for s in v if isinstance(s, str) and s.strip()]
            if vals:
                # de-dup preserve order
                seen = set()
                uniq = []
                for s in vals:
                    if s not in seen:
                        seen.add(s)
                        uniq.append(s)
                out[k] = uniq
        elif typ is bool and isinstance(v, bool):
            out[k] = v
        elif typ is str and isinstance(v, str) and v.strip():
            out[k] = v.strip()

    # Normalize date fields if present
    for dk in ("missing_since", "recovery_date"):
        if dk in out:
            iso = _iso_or_none(out[dk])
            if iso:
                out[dk] = iso
            else:
                # drop invalid date
                out.pop(dk, None)

    # Light logical consistency checks with warnings
    if out.get("recovered") is True and "recovery_date" not in out:
        print("⚠️  [WARN] recovered=true but recovery_date missing")
    if out.get("missing") is True and "missing_since" not in out:
        print("⚠️  [WARN] missing=true but missing_since missing")

    return out


# -------------------- public API --------------------

def extract_accident_info(url: str, out_dir: str | Path | None = None, base_output: str = "artifacts") -> str:
    """
    Extracts meta information from a page and writes accident_info.json.
    Returns the json path.
    """
    if out_dir is None:
        out_path = _ensure_outdir(url, base_output)
    else:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Reading article text: {url}")
    text = _extract_article_text(url)

    print("[INFO] LLM extracting structured accident info")
    obj = _llm_extract(text)
    info = _postprocess(obj)

    # attach minimal source context
    payload = {
        "source_url": url,
        "extracted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **info
    }

    json_path = str(out_path / "accident_info.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"[INFO] ✅ Wrote {json_path}")
    return json_path


# -------------------- CLI --------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {Path(__file__).name} <URL>")
        sys.exit(1)
    extract_accident_info(sys.argv[1])
