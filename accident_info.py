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
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from bs4 import BeautifulSoup
from pathlib import Path

try:
    # optional date normalization helper
    from dateutil import parser as dateparser  # type: ignore
    _HAS_DATEUTIL = True
except Exception:
    _HAS_DATEUTIL = False

from openai import OpenAI
try:
    from config import TIMEZONE, GAZETTEER_ENABLED
except Exception:
    TIMEZONE = 'America/Vancouver'
    GAZETTEER_ENABLED = False
try:
    from store_artifacts import upsert_artifact, init_db
except Exception:
    upsert_artifact = None
    init_db = None
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
    # use PST / America/Los_Angeles for consistent artifact timestamps
    try:
        if ZoneInfo is not None and TIMEZONE:
            ts = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y%m%d_%H%M%S")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    except Exception:
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


def _now_pst_iso() -> str:
    """Return current time formatted in America/Los_Angeles (PST/PDT) as an ISO string (seconds precision)."""
    try:
        if ZoneInfo is not None and TIMEZONE:
            return datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec='seconds')
    except Exception:
        pass
    # fallback to UTC with Z if zoneinfo not available
    return datetime.now(timezone.utc).isoformat(timespec='seconds') + 'Z'


def pre_extract_fields(text: str) -> dict:
    """Deterministic pre-extraction using regexes to reduce LLM surface area.

    Returns a dict of likely fields (dates, simple counts, names+ages, rescue orgs).
    This is intentionally conservative: it's OK to omit values; do not invent.
    """
    out: dict = {}
    if not text or not isinstance(text, str):
        return out

    # simple date-ish patterns (e.g., May 16, 2025 / May 16 / 16 May 2025)
    date_patterns = [r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\d,0-9]{2,20}"]
    dates = []
    for p in date_patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            txt = m.group(0).strip(' ,.')
            dates.append(txt)
    if dates:
        out['pre_dates'] = dates[:3]

    # name + age patterns: "John Smith, 38" or "John Smith, 38," etc.
    people = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}),\s*(\d{1,3})\b", text):
        name = m.group(1).strip()
        age = int(m.group(2))
        people.append({'name': name, 'age': age})
    if people:
        out['people_pre'] = people[:10]

    # unnamed people patterns: '22-year-old woman', 'a 22-year-old man', 'the 22-year-old'
    unnamed = []
    for m in re.finditer(r"\b(\d{1,3})[- ]?year[- ]?old\b(?:\s+([A-Za-z\-]+))?", text, flags=re.IGNORECASE):
        try:
            age = int(m.group(1))
        except Exception:
            continue
        sex = None
        if m.group(2):
            s = m.group(2).lower()
            if s in ('man', 'male', 'boy'):
                sex = 'male'
            elif s in ('woman', 'female', 'girl'):
                sex = 'female'
        person = {'name': 'Unknown', 'age': age}
        if sex:
            person['sex'] = sex
        unnamed.append(person)
    # merge unnamed into people_pre if present, else create
    if unnamed:
        if 'people_pre' in out:
            out['people_pre'].extend(unnamed)
        else:
            out['people_pre'] = unnamed

    # simple counts of killed/dead/ injured / missing
    def find_int(patterns):
        vals = []
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                try:
                    v = int(m.group(1))
                    vals.append(v)
                except Exception:
                    continue
        return vals

    killed = find_int([r"\b(killed)\s+(\d+)\b", r"\b(\d+)\s+killed\b", r"\b(\d+)\s+dead\b"])
    injured = find_int([r"\b(\d+)\s+injured\b", r"(\d+)\s+hurt\b"])
    # fallback patterns: "one person died" (try to map words to numbers for 1..5)
    word_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
    for w, n in word_map.items():
        if re.search(rf"\b{w}\b\s+(?:people\s+)?(?:died|dead|killed)\b", text, flags=re.IGNORECASE):
            killed.append(n)

    if killed:
        out['num_fatalities_pre'] = max(killed)
    if injured:
        out['num_injured_pre'] = max(injured)

    # rescue teams (look for common tokens)
    rescue_tokens = [r"Search and Rescue", r"SAR\b", r"RCMP\b", r"police\b", r"Fire Department", r"EMS\b"]
    rescues = set()
    for t in rescue_tokens:
        for m in re.finditer(t, text, flags=re.IGNORECASE):
            rescues.add(m.group(0).strip())
    if rescues:
        out['rescue_teams_pre'] = list(rescues)

    # area / park heuristics: look for patterns like 'in the X Recreation Area' or 'at X Park'
    area_m = re.search(r"\b(?:in|at)\s+([A-Z][\w\s'\-]{3,80}?(?:Area|Park|Recreation|Range|Provincial))", text)
    if area_m:
        out['area_pre'] = area_m.group(1).strip()

    # gazetteer-based matches (load a small local gazetteer)
    # gazetteer-based matches (load a small local gazetteer) - optional via config
    if GAZETTEER_ENABLED:
        try:
            gaz_path = Path(__file__).parent / 'data' / 'gazetteer_mountains.json'
            if gaz_path.exists():
                import json as _json
                with open(gaz_path, 'r', encoding='utf-8') as _g:
                    gaz = _json.load(_g)
                for name in gaz:
                    if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
                        out.setdefault('gazetteer_matches', []).append(name)
        except Exception:
            pass

    # short summary candidate: first 1-2 sentences
    sents = re.split(r"(?<=[\.\!\?])\s+", text.strip())
    if sents:
        out['lead_sentences'] = sents[:2]

    # route difficulty heuristics (YDS grades, alpine grades, V grades, class ratings)
    diff_patterns = [r"\b5\.[0-9]{1,2}[a-z]?\b", r"\bclass\s+[1-5]\b", r"\bV\d+\b", r"\bGrade\s+[I|II|III|IV|V|VI]\b"]
    diffs = []
    for p in diff_patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            diffs.append(m.group(0))
    if diffs:
        out['route_difficulty_pre'] = list(dict.fromkeys(diffs))

    # route type keywords
    route_types = []
    for kw in ['rappel', 'rappelling', 'couloir', 'gully', 'ridge', 'spire', 'face', 'wall', 'crag', 'route', 'descent', 'ascent']:
        if re.search(rf"\b{kw}\b", text, flags=re.IGNORECASE):
            route_types.append(kw)
    if route_types:
        out['route_types_pre'] = list(dict.fromkeys(route_types))

    # equipment tokens
    equipment = []
    for kw in ['piton', 'anchor', 'pitons', 'harness', 'leash', 'carabiner', 'bolt', 'gps', 'rope', 'piton']:
        if re.search(rf"\b{kw}\b", text, flags=re.IGNORECASE):
            equipment.append(kw)
    if equipment:
        out['equipment_pre'] = list(dict.fromkeys(equipment))

    # fall height extraction (e.g., '400 feet (122 meters)' or '400-foot')
    fh = None
    m = re.search(r"(\d{2,5})\s*(?:feet|ft|foot)\b", text, flags=re.IGNORECASE)
    if m:
        try:
            feet = int(m.group(1))
            meters = round(feet * 0.3048, 1)
            out['fall_height_feet_pre'] = feet
            out['fall_height_meters_pre'] = meters
        except Exception:
            pass

    return out

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

_PROMPT = """
System: You are a precise information extraction assistant. Return VALID JSON only, no prose, no markdown fences. Do NOT invent details.

SCHEMA: Return an object containing any of the following keys (omit keys not present/confident):
    source_url, source_name, article_title, article_date_published (YYYY-MM-DD), region, mountain_name, route_name,
    activity_type, accident_type, accident_date (YYYY-MM-DD), accident_time_approx, num_people_involved (int),
    num_fatalities (int), num_injured (int), num_rescued (int), people (array of objects with name, age, outcome, injuries, rescue_status, hometown),
    rescue_teams_involved (array), response_agencies (array), rescue_method, response_difficulties, bodies_recovery_method,
    accident_summary_text, timeline_text, quoted_dialogue (array), notable_equipment_details, local_expert_commentary,
    family_statements, photo_urls (array), video_urls (array), related_articles_urls (array), fundraising_links (array),
    official_reports_links (array), fall_height_meters_estimate (float), self_rescue_boolean (bool), anchor_failure_boolean (bool),
    extraction_confidence_score (0-1 float)

Guidance:
- Use ONLY evidence present in the provided PRE-EXTRACTED and ARTICLE text. If unsure, omit the key.
- Normalize dates to ISO format when possible; do not fabricate years.
- Keep arrays of strings concise and canonical (e.g., 'Squamish Search and Rescue', 'Sea to Sky RCMP').

PRE-EXTRACTED:
{PRE}

ARTICLE:
{ARTICLE}

Return one JSON object.
"""

def _llm_extract(article_text: str) -> dict:
    # Truncate extremely long pages to keep costs down but keep most relevant content
    content = article_text[:18000]
    pre = pre_extract_fields(article_text)
    if not _OPENAI_AVAILABLE or _client is None:
        print("[WARN] OPENAI_API_KEY not set; skipping LLM extraction")
        return {}

    # Respect per-run OpenAI call cap if configured
    if not can_make_call():
        print("[WARN] OpenAI call cap reached (remaining=0); skipping LLM extraction")
        return {}

    # Build the prompt with PRE-EXTRACTED
    prompt = _PROMPT.format(PRE=json.dumps(pre, ensure_ascii=False, indent=2), ARTICLE=content)
    resp = _client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a precise JSON-only extractor."},
            {"role": "user", "content": [{"type": "text", "text": prompt}]}
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
    """Validate and normalize a broad accident extraction schema.

    This function is conservative: unknown keys are passed through only when they match
    expected types. Dates are normalized to ISO when possible; numeric strings are cast.
    """
    # Define expected types for the extended schema
    expected = {
        # basic metadata
        'source_url': str,
        'source_name': str,
        'article_title': str,
        'article_date_published': str,
        # location/activity
        'region': str,
        'mountain_name': str,
        'route_name': str,
        'activity_type': str,
        'accident_type': str,
        'accident_date': str,
        'accident_time_approx': str,
        # numeric counts
        'num_people_involved': int,
        'num_fatalities': int,
        'num_injured': int,
        'num_rescued': int,
        # people array
        'people': list,
        # arrays of strings
        'rescue_teams_involved': list,
        'response_agencies': list,
        'quoted_dialogue': list,
        'photo_urls': list,
        'video_urls': list,
        'related_articles_urls': list,
        'fundraising_links': list,
        'official_reports_links': list,
        # other strings
        'rescue_method': str,
        'response_difficulties': str,
        'bodies_recovery_method': str,
        'accident_summary_text': str,
        'timeline_text': str,
        'notable_equipment_details': str,
        'local_expert_commentary': str,
        'family_statements': str,
        # floats / booleans
        'fall_height_meters_estimate': float,
        'self_rescue_boolean': bool,
        'anchor_failure_boolean': bool,
        'extraction_confidence_score': float,
    }

    out: dict = {}

    def keep_str(k, v):
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()

    def keep_int(k, v):
        if isinstance(v, int):
            out[k] = v
        elif isinstance(v, str):
            try:
                out[k] = int(v.strip())
            except Exception:
                pass
        elif isinstance(v, float):
            out[k] = int(v)

    def keep_float(k, v):
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, str):
            try:
                out[k] = float(v.strip())
            except Exception:
                pass

    def keep_bool(k, v):
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, str):
            if v.strip().lower() in ('true', 'yes', '1'):
                out[k] = True
            elif v.strip().lower() in ('false', 'no', '0'):
                out[k] = False

    def keep_list_of_str(k, v):
        if isinstance(v, list):
            vals = [s.strip() for s in v if isinstance(s, str) and s.strip()]
            if vals:
                # dedupe preserve order
                seen = set(); uniq = []
                for s in vals:
                    if s not in seen:
                        seen.add(s); uniq.append(s)
                out[k] = uniq
        elif isinstance(v, str) and v.strip():
            out[k] = [v.strip()]

    # iterate keys in the provided object and try to coerce/validate
    for k, v in obj.items():
        if k not in expected:
            # allow passthrough for a few safe keys if they look like strings
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
            continue
        typ = expected[k]
        if typ is str:
            keep_str(k, v)
        elif typ is int:
            keep_int(k, v)
        elif typ is float:
            keep_float(k, v)
        elif typ is bool:
            keep_bool(k, v)
        elif typ is list:
            if k == 'people' and isinstance(v, list):
                people_out = []
                for person in v:
                    if not isinstance(person, dict):
                        continue
                    p = {}
                    # minimal person fields we accept
                    if 'name' in person and isinstance(person['name'], str) and person['name'].strip():
                        p['name'] = person['name'].strip()
                    if 'age' in person:
                        try:
                            p['age'] = int(person['age'])
                        except Exception:
                            pass
                    if 'outcome' in person and isinstance(person['outcome'], str):
                        p['outcome'] = person['outcome'].strip()
                    if 'injuries' in person and isinstance(person['injuries'], str):
                        p['injuries'] = person['injuries'].strip()
                    if p:
                        people_out.append(p)
                if people_out:
                    out['people'] = people_out
            else:
                keep_list_of_str(k, v)

    # Normalize date fields if present
    for dk in ('article_date_published', 'accident_date', 'missing_since', 'recovery_date'):
        if dk in out:
            iso = _iso_or_none(out[dk])
            if iso:
                out[dk] = iso
            else:
                # drop invalid date
                out.pop(dk, None)

    # Validate extraction_confidence_score in 0..1
    if 'extraction_confidence_score' in out:
        try:
            v = float(out['extraction_confidence_score'])
            if 0.0 <= v <= 1.0:
                out['extraction_confidence_score'] = v
            else:
                out.pop('extraction_confidence_score', None)
        except Exception:
            out.pop('extraction_confidence_score', None)

    # some light logical checks
    if out.get('num_fatalities') is not None and out.get('num_people_involved') is not None:
        if out['num_fatalities'] > out['num_people_involved']:
            print('⚠️  [WARN] num_fatalities > num_people_involved; leaving values but check source')

    # prefer gazetteer matches if present in pre-extracted fields
    # If the LLM returned a generic mountain name, but we have a gazetteer match, prefer the gazetteer
    try:
        if 'gazetteer_matches' in obj and obj['gazetteer_matches'] and 'mountain_name' not in out:
            out['mountain_name'] = obj['gazetteer_matches'][0]
        if 'gazetteer_matches' in obj and obj['gazetteer_matches'] and 'region' not in out:
            # try to use the gazetteer first item as a fallback for region
            out.setdefault('region', obj['gazetteer_matches'][0])
    except Exception:
        pass

    return out


def compute_confidence(pre: dict, llm: dict) -> float:
    """Heuristic confidence based on overlap of deterministic pre-extracted evidence and LLM output.

    Scores from 0.0 to 1.0.
    - +0.25 if a date in pre_dates matches accident_date/article_date
    - +0.2 if gazetteer_matches contains mountain_name
    - +0.2 if fall_height_feet_pre correlates within 15% of fall_height_meters_estimate
    - +0.15 if num_fatalities_pre (derived) matches num_fatalities
    - +0.2 if people_pre items corroborate people names/ages in llm
    Cap at 1.0
    """
    score = 0.0
    try:
        # dates
        pd = pre.get('pre_dates', [])
        for d in pd:
            iso = _iso_or_none(d)
            if iso and (llm.get('accident_date') == iso or llm.get('article_date_published') == iso):
                score += 0.25
                break

        # gazetteer
        if pre.get('gazetteer_matches'):
            g0 = pre['gazetteer_matches'][0]
            if llm.get('mountain_name') and g0.lower() in llm.get('mountain_name', '').lower():
                score += 0.2

        # fall height correlation
        if 'fall_height_feet_pre' in pre and 'fall_height_meters_estimate' in llm:
            try:
                feet = float(pre['fall_height_feet_pre'])
                meters_est = float(llm['fall_height_meters_estimate'])
                meters_from_feet = feet * 0.3048
                if abs(meters_from_feet - meters_est) / max(meters_est, 1.0) < 0.15:
                    score += 0.2
            except Exception:
                pass

        # fatalities
        if 'num_fatalities_pre' in pre and 'num_fatalities' in llm:
            try:
                if int(pre['num_fatalities_pre']) == int(llm['num_fatalities']):
                    score += 0.15
            except Exception:
                pass

        # people corroboration (simple name/age overlap)
        if 'people_pre' in pre and 'people' in llm:
            pre_people = pre['people_pre']
            ll_people = llm['people'] if isinstance(llm['people'], list) else []
            matches = 0
            for p in pre_people:
                for q in ll_people:
                    if 'age' in p and 'age' in q and int(p['age']) == int(q.get('age', -1)):
                        matches += 1
                        break
            if matches >= 1:
                score += 0.2
    except Exception:
        pass

    return min(1.0, round(score, 2))


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
    pre = pre_extract_fields(text)
    obj = _llm_extract(text)
    # attach the pre-extracted dict into the object for downstream use
    if isinstance(obj, dict):
        obj['gazetteer_matches'] = pre.get('gazetteer_matches', [])
    info = _postprocess(obj)

    # compute deterministic confidence and prefer it if model did not provide one
    try:
        if 'extraction_confidence_score' not in info or not isinstance(info.get('extraction_confidence_score'), float):
            c = compute_confidence(pre, info)
            info['extraction_confidence_score'] = c
        else:
            # combine model score and deterministic score conservatively
            model_score = float(info.get('extraction_confidence_score'))
            det = compute_confidence(pre, info)
            # weighted average favoring deterministic evidence slightly
            info['extraction_confidence_score'] = round((0.4 * model_score + 0.6 * det), 2)
    except Exception:
        pass

    # attach minimal source context and include the cleaned article text for traceability
    # include both the focused article_text and the full scraped text (before trimming) for traceability
    payload = {
        "source_url": url,
        "extracted_at": _now_pst_iso(),
        "article_text": text,
        "scraped_full_text": full_text,
        **info
    }

    json_path = str(out_path / "accident_info.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # optional DB write (opt-in via env var)
    try:
        if os.getenv('WRITE_TO_DB', 'false').lower() in ('1', 'true', 'yes') and upsert_artifact is not None:
            try:
                init_db() if init_db is not None else None
            except Exception:
                pass
            try:
                upsert_artifact(payload)
            except Exception as e:
                print(f"[WARN] Failed to write artifact to DB: {e}")
    except Exception:
        pass

    print(f"[INFO] ✅ Wrote {json_path}")
    return json_path


def batch_extract_accident_info(urls: list[str], batch_size: int = 3, base_output: str = "artifacts") -> list[str]:
    """Process a list of URLs in batches. For each batch we perform deterministic pre-extraction and then
    make a single LLM call that returns a JSON array of extraction objects. We then postprocess and write
    per-URL `accident_info.json` files under artifacts.

    Returns list of written json paths.
    """
    written = []
    # break into batches
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i+batch_size]
        prints = []
        pre_list = []
        texts = []
        full_texts = []
        out_dirs = []
        for u in batch:
            try:
                od = _ensure_outdir(u, base_output)
            except Exception:
                od = Path(base_output) / _slugify(urlparse(u).netloc.replace('www.', '')) / datetime.now().strftime('%Y%m%d_%H%M%S')
                od.mkdir(parents=True, exist_ok=True)
            out_dirs.append(od)
            # extract text deterministically
            full_text, focused = _extract_article_text(u)
            texts.append(focused)
            full_texts.append(full_text)
            pre = pre_extract_fields(focused)
            pre_list.append(pre)
        # Build a batched prompt asking for an array of JSON objects
        items = []
        for idx, u in enumerate(batch):
            items.append({
                'url': u,
                'pre_extracted': pre_list[idx],
                'article': texts[idx][:12000]
            })

        # Compose prompt: SCHEMA + list of items
        schema = _PROMPT
        payload = {
            'items': items
        }

        # Respect call caps and availability
        if not _OPENAI_AVAILABLE or _client is None:
            print('[WARN] OPENAI_API_KEY not set; skipping batch LLM extraction')
            # still write minimal artifacts with scraped_full_text and pre_extracted
            for idx, u in enumerate(batch):
                payload_write = {
                    'source_url': u,
                    'extracted_at': _now_pst_iso(),
                    'article_text': texts[idx],
                    'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                    'pre_extracted': pre_list[idx]
                }
                p = str(out_dirs[idx] / 'accident_info.json')
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(payload_write, f, indent=2, ensure_ascii=False)
                written.append(p)
            continue

        # check call cap before attempting the batch call
        if not can_make_call():
            print('[WARN] OpenAI call cap reached; skipping LLM batch for this group')
            for idx, u in enumerate(batch):
                payload_write = {
                    'source_url': u,
                    'extracted_at': _now_pst_iso(),
                    'article_text': texts[idx],
                    'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                    'pre_extracted': pre_list[idx]
                }
                p = str(out_dirs[idx] / 'accident_info.json')
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(payload_write, f, indent=2, ensure_ascii=False)
                written.append(p)
            continue

        # single LLM call for the batch
        prompt = "System: Return a JSON array with one extraction object per item. Use the provided PRE-EXTRACTED and ARTICLE fields.\n"
        prompt += json.dumps(payload, ensure_ascii=False)

        try:
            resp = _client.chat.completions.create(
                model='gpt-4o-mini',
                temperature=0,
                messages=[
                    {'role': 'system', 'content': 'You are a precise JSON-only extractor.'},
                    {'role': 'user', 'content': [{'type': 'text', 'text': prompt}]}
                ],
            )
        except Exception as e:
            print(f'[WARN] Batch LLM call failed: {e}')
            continue

        raw = resp.choices[0].message.content.strip()
        arr = None
        # First, try direct parse
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, list):
                arr = candidate
        except Exception:
            pass

        # parsing attempts: direct -> bracket substring -> repair
        try:
            # direct parse
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, list):
                    arr = candidate
            except Exception:
                arr = None

            # bracket substring
            if arr is None:
                s = raw
                start = s.find('[')
                end = s.rfind(']')
                if start != -1 and end != -1 and end > start:
                    try:
                        sub = s[start:end+1]
                        arr = json.loads(sub)
                        if not isinstance(arr, list):
                            arr = None
                    except Exception:
                        arr = None

            # repair pass
            if arr is None:
                repair = _client.chat.completions.create(
                    model='gpt-4o-mini',
                    temperature=0,
                    messages=[{'role': 'user', 'content': [{'type': 'text', 'text': 'Convert the following to a JSON array only:\n' + raw}]}]
                )
                arr = json.loads(repair.choices[0].message.content.strip())

            # record that we used one LLM call for the batch
            try:
                record_call(1)
            except Exception:
                pass
        except Exception:
            print('[WARN] Failed to parse batch LLM response; skipping batch')
            continue

        # postprocess and write per-url artifacts
        # If response length doesn't match batch length, be conservative: iterate up to min length
        min_len = min(len(arr), len(batch))
        if len(arr) != len(batch):
            print(f'[WARN] LLM returned {len(arr)} items for batch of {len(batch)}; aligning to {min_len} items')

        for idx in range(min_len):
            out_obj = arr[idx]
            llm_out = out_obj if isinstance(out_obj, dict) else {}
            info = _postprocess(llm_out)
            # compute deterministic confidence
            try:
                if 'extraction_confidence_score' not in info:
                    info['extraction_confidence_score'] = compute_confidence(pre_list[idx], info)
            except Exception:
                pass
            payload_write = {
                'source_url': batch[idx],
                'extracted_at': _now_pst_iso(),
                'article_text': texts[idx],
                'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                **info
            }
            p = str(out_dirs[idx] / 'accident_info.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(payload_write, f, indent=2, ensure_ascii=False)
            written.append(p)
            # optional DB write for batch items
            try:
                if os.getenv('WRITE_TO_DB', 'false').lower() in ('1', 'true', 'yes') and upsert_artifact is not None:
                    try:
                        init_db() if init_db is not None else None
                    except Exception:
                        pass
                    try:
                        upsert_artifact(payload_write)
                    except Exception as e:
                        print(f"[WARN] Failed to write batch artifact to DB: {e}")
            except Exception:
                pass

    return written


# -------------------- CLI --------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {Path(__file__).name} <URL>")
        sys.exit(1)
    extract_accident_info(sys.argv[1])
