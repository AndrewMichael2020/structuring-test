#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict
import os

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accident_llm import _chat_create as _llm_chat_create, _OPENAI_AVAILABLE
from openai_call_manager import can_make_call, record_call
from config import REPORT_PLANNER_MODEL, REPORT_WRITER_MODEL, REPORT_VERIFIER_MODEL, SERVICE_TIER

from services.report_prompts import (
    PLANNER_SYSTEM,
    PLANNER_USER_TMPL,
    WRITER_SYSTEM_TMPL,
    WRITER_USER_TMPL,
    VERIFIER_SYSTEM,
    VERIFIER_USER_TMPL,
)
from services.report_render import front_matter, as_markdown_timeline, as_table, as_bullets
from token_tracker import add_usage, summary as token_summary


logger = logging.getLogger(__name__)
try:
    logger.addHandler(logging.NullHandler())
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parents[1]
FUSED_DIR = BASE_DIR / 'events' / 'fused'
REPORTS_DIR = BASE_DIR / 'events' / 'reports'


def _load_event(eid: str) -> Dict[str, Any]:
    p = FUSED_DIR / f"{eid}.json"
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _llm_json(model: str, system: str, user_text: str) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [{"type": "text", "text": user_text}]},
    ]
    resp = _llm_chat_create(messages=messages, model=model)
    try:
        record_call(1)
    except Exception:
        pass
    try:
        usage = getattr(resp, 'usage', None)
        if usage is not None:
            try:
                add_usage(int(getattr(usage, 'prompt_tokens', 0) or 0), int(getattr(usage, 'completion_tokens', 0) or 0))
            except Exception:
                pass
    except Exception:
        pass
    return json.loads(resp.choices[0].message.content.strip())


def _llm_text(model: str, system: str, user_text: str) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [{"type": "text", "text": user_text}]},
    ]
    resp = _llm_chat_create(messages=messages, model=model)
    try:
        record_call(1)
    except Exception:
        pass
    try:
        usage = getattr(resp, 'usage', None)
        if usage is not None:
            try:
                add_usage(int(getattr(usage, 'prompt_tokens', 0) or 0), int(getattr(usage, 'completion_tokens', 0) or 0))
            except Exception:
                pass
    except Exception:
        pass
    return resp.choices[0].message.content


def generate_report(eid: str, audience: str = 'climbers', family_sensitive: bool = True, dry_run: bool = False) -> Path | None:
    if not _OPENAI_AVAILABLE or not can_make_call():
        logger.warning('OPENAI unavailable or cap reached; cannot generate report')
        return None
    event = _load_event(eid)

    # ------------------------- Deterministic helpers ------------------------- #
    def _parse_date(s: str) -> datetime | None:
        for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d %b %Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(s[:19], fmt)
            except Exception:
                continue
        return None

    pub_dt: datetime | None = None
    pub_raw = event.get('article_date_published') or event.get('article_date') or ''
    if pub_raw:
        pub_dt = _parse_date(pub_raw)

    WEEKDAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    MONTHS = {m.lower(): i for i,m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'], start=1)}

    article_text = event.get('article_text') or event.get('scraped_full_text') or ''

    def infer_event_date() -> str:
        # Priority 1: explicit upstream accident_date
        acc = (event.get('accident_date') or '').strip()
        if acc:
            return acc
        text = article_text
        lowered = text.lower()
        # Priority 2: weekday mention + publication date → choose most recent past weekday
        if pub_dt:
            for wd in WEEKDAYS:
                if re.search(rf"\b{wd}\b", lowered):
                    # go back up to 7 days to find that weekday
                    target = pub_dt
                    for _ in range(7):
                        if target.strftime('%A').lower() == wd:
                            return target.strftime('%Y-%m-%d') + ' (approx, inferred from weekday reference)'
                        target = target - timedelta(days=1)
                    break
        # Priority 3: Month + Day + (optional Year)
        # Capture patterns like 'July 23, 2022' or 'July 23' or '23 July 2022'
        md_pattern = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-3]?\d)(?:,?\s+(\d{4}))?', re.IGNORECASE)
        m = md_pattern.search(text)
        if m:
            month_name, day, year = m.group(1), m.group(2), m.group(3)
            if year:
                return f"{year}-{int(MONTHS[month_name.lower()]):02d}-{int(day):02d}"
            # no year: estimate relative to publication date if available
            if pub_dt:
                y = pub_dt.year
                candidate = datetime(y, MONTHS[month_name.lower()], int(day))
                # if candidate is > pub_dt (future), assume previous year
                if candidate > pub_dt:
                    candidate = datetime(y - 1, MONTHS[month_name.lower()], int(day))
                if (pub_dt - candidate).days <= 366:
                    return candidate.strftime('%Y-%m-%d') + ' (year inferred)'
            return f"Specific date known (month/day: {month_name} {day}, year unknown)"
        # Priority 4: Month + Year (no specific day)
        my_pattern = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', re.IGNORECASE)
        my = my_pattern.search(text)
        if my:
            month_name, year = my.group(1), my.group(2)
            return f"Specific date known (month/year: {month_name} {year})"
        # Priority 5: Month only
        mo_pattern = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)', re.IGNORECASE)
        mo = mo_pattern.search(text)
        if mo and pub_dt:
            month_name = mo.group(1)
            # assume within last 12 months
            y = pub_dt.year
            candidate = datetime(y, MONTHS[month_name.lower()], 1)
            if candidate > pub_dt:
                candidate = datetime(y - 1, MONTHS[month_name.lower()], 1)
            return candidate.strftime('%Y-%m') + ' (month inferred)'
        return 'Specific date unknown'

    inferred_date = infer_event_date()

    def infer_region() -> str:
        for k in ('mountain_name','peak','area_name','location','region'):
            v = event.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ''

    # Extract web links (sources)
    def extract_links() -> list[str]:
        links = set()
        # upstream list
        for key in ('source_urls','source_url','sources'):
            v = event.get(key)
            if isinstance(v, list):
                for s in v:
                    if isinstance(s, str) and s.startswith('http'):
                        links.add(s.strip())
            elif isinstance(v, str) and v.startswith('http'):
                links.add(v.strip())
        # fallback: regex scan article text
        for m in re.findall(r'https?://[^\s)]+', article_text):
            links.add(m.rstrip(').,'))
        return sorted(links)

    web_links = extract_links()

    # Build a compact sources block for final markdown (explicit ordering)
    def render_sources_block() -> str:
        if not web_links:
            return ''
        agencies = []
        for k in ('response_agencies','rescue_teams_involved','agencies'):
            v = event.get(k)
            if isinstance(v, list):
                agencies.extend([a for a in v if isinstance(a, str)])
        # Deduplicate agencies preserving order
        seen = set()
        dedup_agencies = []
        for a in agencies:
            if a not in seen:
                seen.add(a)
                dedup_agencies.append(a)
        block = ["## Sources", *web_links]
        if dedup_agencies:
            block.append("Agencies: " + '; '.join(dedup_agencies))
        return '\n'.join(block) + '\n'

    # Short title generation via lightweight LLM (planner model) for speed
    def generate_short_title() -> str:
        try:
            prompt = (
                "Produce a concise, down-to-earth incident title (<=8 words, no date) describing the event. "
                "Avoid sensationalism; include key location or activity if possible. Return ONLY the title text.\n\n"
                f"EVENT JSON:\n{json.dumps(event, ensure_ascii=False)}"
            )
            resp = _llm_text(REPORT_PLANNER_MODEL, "You write concise neutral titles.", prompt)
            title = resp.strip().split('\n')[0].strip('# ').strip()
            # basic cleanup
            if len(title) > 120:
                title = title[:117] + '...'
            return title or 'Mountaineering Incident'
        except Exception:
            pass
        # deterministic fallback
        loc = infer_region() or 'Mountaineering'
        acc_type = event.get('accident_type') or 'Incident'
        return f"{loc} {acc_type}".strip()

    short_title = generate_short_title()

    # Planner (mini)
    outline = _llm_json(
        REPORT_PLANNER_MODEL,
        PLANNER_SYSTEM,
        PLANNER_USER_TMPL.format(EVENT_JSON=json.dumps(event, ensure_ascii=False))
    )

    # Writer (GPT-5)
    writer_system = WRITER_SYSTEM_TMPL.format(audience=audience, family_sensitive=str(family_sensitive).lower())
    # Prefer a concise place/peak hint for the H1 title
    title_hint = (
        event.get('mountain_name')
        or event.get('peak')
        or event.get('area_name')
        or event.get('location')
        or event.get('region')
        or 'Mountaineering'
    )
    draft_md = _llm_text(
        REPORT_WRITER_MODEL,
        writer_system,
        WRITER_USER_TMPL.format(
            TITLE_HINT=title_hint,
            OUTLINE_JSON=json.dumps(outline, ensure_ascii=False),
            EVENT_JSON=json.dumps(event, ensure_ascii=False),
        ),
    )

    # Verifier (mini)
    verify = _llm_json(
        REPORT_VERIFIER_MODEL,
        VERIFIER_SYSTEM,
        VERIFIER_USER_TMPL.format(family_sensitive=str(family_sensitive).lower(), EVENT_JSON=json.dumps(event, ensure_ascii=False), DRAFT=draft_md)
    )
    # For now we don't apply redactions automatically; we can append issues at the end

    # Compose a clean title: prefer explicit 'title' in fused record, then mountain/area and activity
    title_seed = event.get('title') or event.get('mountain_name') or event.get('area_name') or event.get('location') or event.get('region')
    # If title_seed is a dict (sometimes the fused record stores a nested location), stringify useful parts
    if isinstance(title_seed, dict):
        parts = []
        for k in ('area_name','nearby','region'):
            v = title_seed.get(k)
            if v:
                parts.append(str(v))
        title_seed = ', '.join(parts) if parts else 'Unknown'
    meta = {
        'title': short_title,
        'date_of_event': inferred_date,
        'region': infer_region(),
        'audience': audience,
        'event_id': event.get('event_id') or eid,
    }
    header = front_matter(meta)
    final_md = header + "\n" + draft_md

    # Insert web links section if not already present
    # Append or replace sources section at end for consistent layout
    sources_block = render_sources_block()
    if sources_block:
        if '## Sources' in final_md:
            # Replace existing block crudely by appending refined block if not present already
            if sources_block not in final_md:
                final_md += '\n' + sources_block
        else:
            final_md += '\n' + sources_block

    if dry_run:
        return None
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    outp = REPORTS_DIR / f"{eid}.md"
    with open(outp, 'w', encoding='utf-8') as f:
        f.write(final_md)
    # Print token summary for report generation step
    try:
        s = token_summary()
        logger.info(f"[tokens] reports prompt={s['prompt']}, completion={s['completion']}, total={s['total']}")
    except Exception:
        pass
    return outp


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='Generate Markdown reports per fused event.')
    parser.add_argument('--event-id', type=str, help='Specific event_id to render (default: all)')
    parser.add_argument('--audience', choices=['climbers','general'], default='climbers')
    parser.add_argument('--family-sensitive', action='store_true', help='Enable sensitive tone/redactions')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if args.event_id:
        target_ids = [args.event_id]
    else:
        target_ids = [p.stem for p in FUSED_DIR.glob('*.json')]
    wrote = 0
    for eid in target_ids:
        p = generate_report(eid, audience=args.audience, family_sensitive=args.family_sensitive, dry_run=args.dry_run)
        if p:
            wrote += 1
            print(f"[report] wrote {p}")
    print(f"[models] planner={REPORT_PLANNER_MODEL}, writer={REPORT_WRITER_MODEL}, verifier={REPORT_VERIFIER_MODEL}, tier={SERVICE_TIER}")
    print(f"✅ Reports: {wrote}/{len(target_ids)} written{' (dry-run)' if args.dry_run else ''}.")

    # If we actually wrote reports (not dry-run), attempt to build & upload the
    # canonical `reports/list.json` to the configured GCS bucket. This is
    # best-effort and intentionally non-fatal to avoid blocking report
    # generation on upload issues.
    try:
        # Only attempt upload when reports were actually written and a bucket
        # is configured. This avoids running the builder when nothing changed.
        if wrote > 0 and not args.dry_run and os.environ.get('GCS_BUCKET'):
            import subprocess
            builder = Path(ROOT) / 'scripts' / 'build_reports_list.py'
            print(f"Building and uploading reports/list.json via {builder}")
            subprocess.check_call([sys.executable, str(builder), '--upload'])
    except Exception as e:
        print(f"[warn] failed to upload reports/list.json: {e}")
