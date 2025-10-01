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
import hashlib
from urllib.parse import urlparse
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from pathlib import Path
import logging

# Attempt to load a .env file in the project directory so os.getenv sees local keys (e.g., OPENAI_API_KEY)
try:
    # prefer python-dotenv if available
    from dotenv import load_dotenv  # type: ignore
    # load .env located next to this file, then fall back to working dir
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    else:
        # fall back to default search behavior
        load_dotenv(override=False)
except Exception:
    # If python-dotenv isn't installed, try a minimal manual parse of a .env file so
    # local development still works without the dependency.
    try:
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as _f:
                for line in _f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    # remove surrounding quotes if present
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    # only set if not already present in env
                    if k and not os.getenv(k):
                        os.environ[k] = v
    except Exception:
        # best-effort only
        pass

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
from openai_call_manager import can_make_call, record_call
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

try:
    from fetcher import extract_article_text as _extract_article_text
except Exception:
    # fallback: provide a minimal wrapper that returns empty strings so tests that import
    # this module don't break if fetcher can't be imported (e.g., missing deps)
    def _extract_article_text(url: str, timeout: int = 25):
        return "", "", url

# module logger
logger = logging.getLogger(__name__)
try:
    logger.addHandler(logging.NullHandler())
except Exception:
    pass


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
        logger.warning("OPENAI_API_KEY not set; skipping LLM extraction")
        return {}

    # Respect per-run OpenAI call cap if configured
    if not can_make_call():
        logger.warning("OpenAI call cap reached (remaining=0); skipping LLM extraction")
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
                seen = set()
                uniq = []
                for s in vals:
                    if s not in seen:
                        seen.add(s)
                        uniq.append(s)
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
            logger.warning('⚠️  num_fatalities > num_people_involved; leaving values but check source')

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

    logger.info(f"Reading article text: {url}")
    # Ensure Playwright nav timeout is capped at 25s via env variable handling
    try:
        os.environ['PLAYWRIGHT_NAV_TIMEOUT_MS'] = str(min(int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','25000')), 25000))
    except Exception:
        os.environ['PLAYWRIGHT_NAV_TIMEOUT_MS'] = '25000'
    # fetch article text and final navigated URL
    res = _extract_article_text(url)
    # support legacy 2-tuple returns (full_text, focused_text) used in tests/mocks
    if isinstance(res, tuple) and len(res) == 3:
        full_text, text, final_url = res
    elif isinstance(res, tuple) and len(res) == 2:
        full_text, text = res
        final_url = url
    else:
        # unexpected shape: fallback
        try:
            full_text, text = res
            final_url = url
        except Exception:
            full_text, text, final_url = '', '', url

    logger.info("LLM extracting structured accident info")
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
    # Build payload but ensure the canonical URL passed to the function wins
    payload = {
        "extracted_at": _now_pst_iso(),
        "article_text": text,
        "scraped_full_text": full_text,
        **info,
        "source_url": final_url or url  # Use final_url when available
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
                logger.warning(f"Failed to write artifact to DB: {e}")
    except Exception:
        pass

    logger.info(f"✅ Wrote {json_path}")
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
        pre_list = []
        texts = []
        full_texts = []
        out_dirs = []
        final_urls = []
        for u in batch:
            try:
                od = _ensure_outdir(u, base_output)
            except Exception:
                od = Path(base_output) / _slugify(urlparse(u).netloc.replace('www.', '')) / datetime.now().strftime('%Y%m%d_%H%M%S')
                od.mkdir(parents=True, exist_ok=True)
            out_dirs.append(od)
            # extract text deterministically; accept either (full, focused) or (full, focused, final_url)
            res = _extract_article_text(u)
            if isinstance(res, tuple) and len(res) == 3:
                full_text, focused, final_u = res
            elif isinstance(res, tuple) and len(res) == 2:
                full_text, focused = res
                final_u = u
            else:
                try:
                    full_text, focused = res
                    final_u = u
                except Exception:
                    full_text, focused, final_u = '', '', u
            texts.append(focused)
            full_texts.append(full_text)
            final_urls.append(final_u or u)
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
        payload = {
            'items': items
        }

        # Respect call caps and availability
        if not _OPENAI_AVAILABLE or _client is None:
            logger.warning('OPENAI_API_KEY not set; skipping batch LLM extraction')
            # still write minimal artifacts with scraped_full_text and pre_extracted
            for idx, u in enumerate(batch):
                payload_write = {
                    'extracted_at': _now_pst_iso(),
                    'article_text': texts[idx],
                    'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                    'pre_extracted': pre_list[idx]
                }
                # ensure canonical URL is preserved (LLM output should not override)
                payload_write['source_url'] = final_urls[idx] if idx < len(final_urls) and final_urls[idx] else u
                p = str(out_dirs[idx] / 'accident_info.json')
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(payload_write, f, indent=2, ensure_ascii=False)
                written.append(p)
            continue

        # check call cap before attempting the batch call
        if not can_make_call():
            logger.warning('OpenAI call cap reached; skipping LLM batch for this group')
            for idx, u in enumerate(batch):
                payload_write = {
                    'source_url': final_urls[idx] if idx < len(final_urls) and final_urls[idx] else u,
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
            logger.warning(f'Batch LLM call failed: {e}')
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
            logger.warning('Failed to parse batch LLM response; skipping batch')
            continue

        # postprocess and write per-url artifacts
        # If response length doesn't match batch length, be conservative: iterate up to min length
        min_len = min(len(arr), len(batch))
        if len(arr) != len(batch):
            logger.warning(f'LLM returned {len(arr)} items for batch of {len(batch)}; aligning to {min_len} items')

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
                'extracted_at': _now_pst_iso(),
                'article_text': texts[idx],
                'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                **info
            }
            # Force canonical source_url from the batch URL (prevent LLM override)
            payload_write['source_url'] = batch[idx]
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
                        logger.warning(f"Failed to write batch artifact to DB: {e}")
            except Exception:
                pass

    return written


# -------------------- CLI --------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        logger.info(f"Usage: python {Path(__file__).name} <URL>")
        sys.exit(1)
    extract_accident_info(sys.argv[1])
