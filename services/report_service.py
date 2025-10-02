#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

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
from services.report_render import front_matter, json_ld, as_markdown_timeline, as_table, as_bullets
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
        'title': f"{title_seed} — {event.get('accident_type','Incident')} ({event.get('accident_date','')})",
        'description': event.get('accident_summary_text') or '',
        'date': event.get('accident_date') or '',
        'region': event.get('region') or '',
        'audience': audience,
        'event_id': event.get('event_id') or eid,
    }
    header = front_matter(meta)
    ld = json_ld(event)
    # omit appendix section per requirement; issues can be used for CI/linting instead
    final_md = header + ld + "\n" + draft_md

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
