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
from openai_call_manager import can_make_call, record_call, remaining
try:
    # reuse resilient fetch helper when available to avoid duplicate retry logic
    from extract_captions import get_with_retries
except Exception:
    get_with_retries = None
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if _OPENAI_API_KEY:
    try:
        _client = OpenAI()
        _OPENAI_AVAILABLE = True
    except Exception:
        _client = None
        _OPENAI_AVAILABLE = False
else:
    _client = None
    _OPENAI_AVAILABLE = False

# Toggle whether to inject a small stealth/init script into Playwright contexts.
# Set PLAYWRIGHT_STEALTH=0/false to disable if it causes compatibility issues.
PLAYWRIGHT_STEALTH = os.getenv("PLAYWRIGHT_STEALTH", "true").lower() in ("1", "true", "yes")

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

def _extract_article_text(url: str, timeout: int = 25) -> tuple[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (GitHub Codespaces; +metadata-extractor)"
    }
    try:
        if get_with_retries is not None:
            resp = get_with_retries(url, timeout=timeout, headers=headers)
            html = resp.text
        else:
            html = requests.get(url, headers=headers, timeout=timeout).text
    except Exception as e:
        print(f"[WARN] Failed to fetch article HTML for {url}: {e}")
        return ""
    # quick bot-block detection: some CDNs return a 403 page or short 'Access Denied' HTML
    soup = BeautifulSoup(html, "html.parser")
    body_text = ' '.join([t.strip() for t in soup.stripped_strings])
    if (resp is not None and getattr(resp, 'status_code', None) == 403) or len(body_text) < 100 or 'access denied' in body_text.lower() or '403 forbidden' in body_text.lower():
        # fallback to Playwright-rendered extraction when site uses JS protection (Akamai/Postmedia etc.)
        try:
            from playwright.sync_api import sync_playwright
            print(f"[INFO] Static fetch appears blocked (status={getattr(resp,'status_code',None)}). Falling back to Playwright for {url}")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
                context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36', viewport={'width':1200,'height':800}, extra_http_headers={'referer': url})
                try:
                    if PLAYWRIGHT_STEALTH:
                        context.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', {get: () => false}); }")
                except Exception:
                    pass
                page = context.new_page()
                page.set_default_navigation_timeout(int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')))
                try:
                    page.goto(url, timeout=int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')), wait_until='domcontentloaded')
                    try:
                        page.wait_for_load_state('networkidle', timeout=int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')))
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[WARN] Playwright navigation failed: {e}")
                    browser.close()
                    # fall back to whatever static body we have
                    soup = BeautifulSoup(html, 'html.parser')
                    return _clean_text_blocks(' '.join([t.strip() for t in soup.stripped_strings]))

                # scroll to load lazy content
                try:
                    page.evaluate("async () => { const delay=(ms)=>new Promise(r=>setTimeout(r,ms)); for(let y=0;y<document.body.scrollHeight;y+=window.innerHeight){ window.scrollTo(0,y); await delay(200);} await delay(300);}"
                    )
                except Exception:
                    pass
                rendered = page.content()
                browser.close()
                soup = BeautifulSoup(rendered, 'html.parser')
        except Exception as e:
            print(f"[WARN] Playwright fallback failed: {e}")
            # if Playwright isn't available or failed, continue with original soup
            soup = BeautifulSoup(html, "html.parser")

    # Prefer article containers; also try to find a title and use only its nearby paragraphs
    candidates = []
    for sel in [
        "article",
        "div.entry-content",
        "div.post-content",
        "main",
        "div#content",
        "div.content",
    ]:
        node = soup.select_one(sel)
        if node:
            candidates.append(node)

    # If we found a clear article container, prefer it
    node = candidates[0] if candidates else None
    if node is None:
        # Choose the DOM element containing the largest amount of paragraph text.
        best = None
        best_len = 0
        for el in soup.find_all(['article', 'section', 'div']):
            ps = el.find_all('p')
            total = sum(len(p.get_text(' ', strip=True) or '') for p in ps)
            if total > best_len:
                best_len = total
                best = el
        if best is not None and best_len > 200:
            node = best
        else:
            node = soup.body or soup

    # collect paragraphs and headings only (avoid nav/footers)
    blocks = []

    # attempt to preserve an explicit title and author/date lines when available
    title = None
    for h in node.find_all(['h1', 'h2']):
        t = h.get_text(' ', strip=True)
        if t and len(t) > 10:
            title = t
            break

    # common boilerplate tokens we want to ignore
    BOILER_TOKENS = [
        'subscribe now', 'sign in', 'create an account', 'unlimited online access',
        'get exclusive access', 'support local journalists', 'daily puzzles', 'share this story',
        'advertisement', 'postmedia is committed', 'comments may take', 'conversation all comments',
        'copy link', 'email', 'reddit', 'pinterest', 'linkedin', 'tumblr', 'save this article',
        'start your day with', 'interested in more newsletters', 'you can save this article',
        'please provide a valid email address'
    ]

    seen_blocks = set()
    for el in node.find_all(["p", "h1", "h2", "h3", "li"]):
        t = el.get_text(" ", strip=True)
        if not t or len(t) < 30:
            # skip very short UI fragments
            continue
        tl = t.lower()
        # stop if we've reached the comments or conversation section
        if tl.startswith('conversation') or tl.startswith('comments') or 'comment by' in tl:
            break
        # skip blocks that look like share/subscribe/ads/prompts
        skip = False
        for token in BOILER_TOKENS:
            if token in tl:
                skip = True
                break
        if skip:
            continue
        # dedupe repeated article fragments
        if t in seen_blocks:
            continue
        seen_blocks.add(t)
        blocks.append(t)

    # If we didn't find a title inside the chosen node, try global headings
    if not title:
        for h in soup.find_all(['h1', 'h2']):
            t = h.get_text(' ', strip=True)
            if t and len(t) > 10:
                title = t
                break

    # Build the full scraped text (deduped blocks, minimal cleaning)
    raw_full = " ".join(blocks)

    # Remove obvious boilerplate/marketing/sidebar lines from the full text while preserving author/date lines
    STOP_TOKENS = [
        'enjoy insights', 'access articles from across canada', 'share your thoughts', 'join the conversation',
        'enjoy additional articles', 'by signing up', 'you consent', 'sign in', 'subscribe now', 'start your day', 'interested in more newsletters',
        'story continues below', 'advertisement', 'this advertisement', 'loading', 'article content', 'related', 'newsletter',
        'youremail', 'photo by', 'comments', '1 minute read', 'please try again', 'we encountered an issue signing',
        'the next issue', 'sunrise', 'start your day with', 'access articles from across canada with one account', 'sign up'
    ]

    # tighten: treat lines that start with short site tags (e.g., "Related: ...") as stop tokens
    STOP_PREFIXES = ['related:', 'you might also like', 'more on', 'from our partners', 'related stories', 'related coverage']

    full_blocks = []
    for b in blocks:
        bl = b.lower()
        # preserve author/published lines explicitly (only when 'By' is followed by a capitalized name)
        if re.match(r'^(author\b|by\s+[A-Z][\w\-\']+)', b.strip()):
            full_blocks.append(b)
            continue
        if re.search(r'published\s', bl) or re.search(r'last updated', bl):
            full_blocks.append(b)
            continue
        # drop lines that begin with explicit related prefixes
        if any(bl.startswith(pfx) for pfx in STOP_PREFIXES):
            continue
        # filter obvious boilerplate
        if any(tok in bl for tok in STOP_TOKENS):
            continue
        # skip very short UI fragments like 'Loading...' or single-word site tags
        if len(b.strip()) < 30:
            # keep short sentences that look like headlines (start with capital and contain a space)
            if not (len(b.strip()) >= 30 or re.match(r'^[A-Z][\w\s\'’:-]+$', b.strip())):
                continue
        full_blocks.append(b)

    # Trim trailing unrelated site headlines/related-articles: keep up to last substantive paragraph.
    substantive_tokens = ['coroners', 'investigation', 'harness', 'leash', 'recovery', 'recovered', 'found', 'fell', 'died', 'death', 'coroner', 'submitted', 'report', 'search and rescue', 'squad', 'rcmp']
    last_idx = None
    for i, b in enumerate(full_blocks):
        bl = b.lower()
        if any(tok in bl for tok in substantive_tokens):
            last_idx = i
    if last_idx is not None:
        full_blocks = full_blocks[: last_idx + 1]

    # join preserved blocks into paragraphs
    # Include title as the first paragraph if present
    para_blocks = []
    if title:
        para_blocks.append(title.strip())
    para_blocks.extend([b.strip() for b in full_blocks if b and b.strip()])
    full_text = "\n\n".join(para_blocks)

    # Remove common one-line newsletter/signup fragments left inside paragraphs
    full_text = re.sub(r"By signing up[\s\S]*?(?=\n\n|$)", "", full_text, flags=re.IGNORECASE)
    full_text = re.sub(r"The next issue of [^\.\n]+will soon be in your inbox[\s\S]*?(?=\n\n|$)", "", full_text, flags=re.IGNORECASE)
    full_text = re.sub(r"By signing up you consent[\s\S]*?(?=\n\n|$)", "", full_text, flags=re.IGNORECASE)

    # After removing, collapse multiple blank lines
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    # If an author email is present, trim after it (common site pattern)
    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", full_text)
    if email_m:
        full_text = full_text[: email_m.end()].strip()
    else:
        # Otherwise, keep up to the last substantive paragraph (by tokens)
        paras = [p.strip() for p in full_text.split('\n\n') if p.strip()]
        last_para_idx = None
        for i, p in enumerate(paras):
            pl = p.lower()
            if any(tok in pl for tok in substantive_tokens):
                last_para_idx = i
        if last_para_idx is not None:
            paras = paras[: last_para_idx + 1]
            full_text = '\n\n'.join(paras)

    # Remove common newsletter/signup fragments that often appear mid-article
    full_text = re.sub(r"By signing up[\s\S]*?Please try again", "", full_text, flags=re.IGNORECASE)
    full_text = re.sub(r"You (have )?been (signed up|subscribed)[\s\S]*?", "", full_text, flags=re.IGNORECASE)

    # Remove trailing related headlines often appended by the site (short repeated headlines)
    # heuristics: many short sentences separated by punctuation repeated; strip them after the main article
    # Final pass: if the last paragraphs look like a short run of related headlines, strip them
    paras = [p.strip() for p in full_text.split('\n\n') if p.strip()]
    # detect trailing short-run headlines: 3+ paras of <=12 words each
    tail_run = 0
    for p in reversed(paras):
        if len(re.findall(r"\w+", p)) <= 12:
            tail_run += 1
        else:
            break
    if tail_run >= 3:
        paras = paras[:-tail_run]
    full_text = '\n\n'.join(paras)

    # If we have many blocks, try to focus on the main article by finding an anchor block
    anchor_regex = re.compile(r"\b(slackline|fell|died|death|fatal|RCMP|Coroners|recovery|highliner|Search and Rescue|recover)\b", re.IGNORECASE)
    anchor_idx = None
    for i, b in enumerate(blocks):
        if anchor_regex.search(b):
            anchor_idx = i
            break

    if anchor_idx is not None:
        start = max(0, anchor_idx - 1)
        end = min(len(blocks), anchor_idx + 6)
        focused = blocks[start:end]
    else:
        focused = blocks

    # Remove common marketing/subscribe/related lines from the focused window
    CLEAN_TOKENS = [
        'enjoy insights', 'access articles from across canada', 'share your thoughts', 'join the conversation',
        'enjoy additional articles', 'by signing up', 'create an account', 'sign in', 'subscribe now',
        'start your day', 'interested in more newsletters', 'story continues below', 'advertisement',
        'this advertisement', 'big cuts are coming', 'what\'s open and closed', 'news', 'local news'
    ]
    final = []
    for b in focused:
        bl = b.lower()
        if any(tok in bl for tok in CLEAN_TOKENS):
            continue
        # drop lines that look like related headlines (very short but title-like)
        if len(b) < 60 and re.match(r"^[A-Z][\w\s'’:-]+$", b) and ' ' in b:
            # possible headline - skip to avoid related article headlines
            continue
        final.append(b)

    text = " ".join(final)
    focused_text = _clean_text_blocks(text)
    full_text = _clean_text_blocks(full_text)
    return full_text, focused_text


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
    if not _OPENAI_AVAILABLE or _client is None:
        print("[WARN] OPENAI_API_KEY not set; skipping LLM extraction")
        return {}

    # Respect per-run OpenAI call cap if configured
    if not can_make_call():
        print("[WARN] OpenAI call cap reached (remaining=0); skipping LLM extraction")
        return {}

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
    # record that we made one OpenAI call
    try:
        record_call(1)
    except Exception:
        pass
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
        # record the repair call as well
        try:
            record_call(1)
        except Exception:
            pass
    except Exception:
        pass
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
    # Ensure Playwright nav timeout is capped at 25s via env variable handling
    try:
        os.environ['PLAYWRIGHT_NAV_TIMEOUT_MS'] = str(min(int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','25000')), 25000))
    except Exception:
        os.environ['PLAYWRIGHT_NAV_TIMEOUT_MS'] = '25000'
    full_text, text = _extract_article_text(url)

    print("[INFO] LLM extracting structured accident info")
    obj = _llm_extract(text)
    info = _postprocess(obj)

    # attach minimal source context and include the cleaned article text for traceability
    # include both the focused article_text and the full scraped text (before trimming) for traceability
    payload = {
        "source_url": url,
        "extracted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "article_text": text,
        "scraped_full_text": full_text,
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
