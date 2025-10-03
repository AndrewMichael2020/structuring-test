#!/usr/bin/env python3
"""Event merge & fusion service.

Stages:
 0) Assume event_id assignment already completed (event_id_service.py)
 1) Group accident_info.json records by event_id
 2) Per event: low-cost merge of text + OCR-derived cues using EVENT_MERGE_MODEL
 3) If multiple sources for the same event_id: deterministic fusion; if conflicts
    remain, synthesize with EVENT_FUSION_MODEL

Outputs (filesystem-only, no DB):
  - events/enriched/{event_id}.json  (merged text+OCR per event)
  - events/fused/{event_id}.json     (final canonical record across sources)

CLI:
  python event_merge_service.py                   # run full merge+fusion
  python event_merge_service.py --dry-run         # compute only, no writes
  python event_merge_service.py --cache-clear     # clear caches and recompute

"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import hashlib

from accident_llm import _chat_create as _llm_chat_create, _OPENAI_AVAILABLE
from openai_call_manager import can_make_call, record_call
from config import EVENT_MERGE_MODEL, EVENT_FUSION_MODEL, SERVICE_TIER
from token_tracker import add_usage

# Best-effort .env loading
try:
    from dotenv import load_dotenv  # type: ignore
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    else:
        load_dotenv(override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)
try:
    logger.addHandler(logging.NullHandler())
except Exception:
    pass


BASE_DIR = Path(__file__).parent
ARTIFACTS_DIR = BASE_DIR / 'artifacts'
EVENTS_DIR = BASE_DIR / 'events'
ENRICHED_DIR = EVENTS_DIR / 'enriched'
FUSED_DIR = EVENTS_DIR / 'fused'
ENRICH_CACHE = BASE_DIR / 'event_merge_cache.json'
FUSE_CACHE = BASE_DIR / 'event_fusion_cache.json'


def _iter_accident_jsons(root: Path) -> List[Path]:
    return [p for p in root.rglob('accident_info.json') if p.is_file()]


def _load_json(p: Path) -> dict | None:
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _group_by_event_id(paths: List[Path]) -> Dict[str, List[Path]]:
    groups: Dict[str, List[Path]] = {}
    for p in paths:
        data = _load_json(p)
        if not data:
            continue
        eid = data.get('event_id')
        if not eid:
            # Skip if unassigned; could log
            continue
        groups.setdefault(eid, []).append(p)
    return groups


def _choose_baseline(records: List[dict]) -> dict:
    # Pick the record with the highest extraction_confidence_score as baseline
    best = None
    best_score = -1.0
    for r in records:
        try:
            s = float(r.get('extraction_confidence_score', 0) or 0)
        except Exception:
            s = 0.0
        if s > best_score:
            best, best_score = r, s
    return best or (records[0] if records else {})


def _load_group_records(paths: List[Path]) -> List[dict]:
    recs: List[dict] = []
    for p in paths:
        d = _load_json(p)
        if d:
            d['__file_path'] = str(p)
            recs.append(d)
    return recs


def _extract_ocr_sidecar(run_dir: Path) -> dict | None:
    # If captions.json exists and contains OCR/Vision enrichments, load it
    cap = run_dir / 'captions.json'
    if not cap.exists():
        return None
    try:
        with open(cap, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _should_ocr_merge(ocr: dict | None) -> bool:
    if not ocr:
        return False
    try:
        esc = float(ocr.get('extraction_confidence_score', 0) or 0)
    except Exception:
        esc = 0.0
    if esc < 0.1:
        return False
    # Check for meaningful enrichments
    dm = ocr.get('derived_metrics')
    ev = ocr.get('events') or ocr.get('event_chain')
    return bool(dm or ev)


def _merge_prompt(baseline: dict, ocr: dict) -> str:
    return (
        "You are a careful JSON merger. Merge OCR/viz cues into BASE, preserving BASE fields, "
        "unioning arrays (no duplicates), and only overwriting scalars if OCR provides clearer/more specific values.\n\n"
        f"BASE:\n{json.dumps(baseline, ensure_ascii=False)}\n\n"
        f"OCR:\n{json.dumps(ocr, ensure_ascii=False)}\n\n"
        "Return VALID JSON only."
    )


def _fuse_prompt(records: List[dict]) -> str:
    return (
        "Fuse these per-source event JSON objects into one canonical record. Resolve conflicts, "
        "union arrays without duplicates, preserve provenance when available, and prefer higher-confidence fields.\n\n"
        f"RECORDS:\n{json.dumps(records, ensure_ascii=False)}\n\n"
        "Return VALID JSON only."
    )


def _cache_load(p: Path) -> Dict[str, Any]:
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _cache_save(p: Path, data: Dict[str, Any]):
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _sig(*objs: Any) -> str:
    m = hashlib.md5()
    for o in objs:
        m.update(json.dumps(o, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    return m.hexdigest()


def _normalize_repo_relative_paths(obj: Any) -> Any:
    """Walk the object and normalize any absolute file paths under this repo
    to repo-root-relative form, e.g., '/artifacts/...' instead of
    '/workspaces/structuring-test/artifacts/...'.
    """
    prefix = str(BASE_DIR)
    def norm_str(s: str) -> str:
        if s.startswith(prefix):
            rel = s[len(prefix):]
            # ensure it starts with '/'
            if not rel.startswith('/'):
                rel = '/' + rel
            return rel
        return s
    if isinstance(obj, dict):
        return {k: _normalize_repo_relative_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_repo_relative_paths(v) for v in obj]
    if isinstance(obj, str):
        return norm_str(obj)
    return obj


def merge_event(eid: str, paths: List[Path], dry_run: bool, merge_cache: Dict[str, Any]) -> dict | None:
    recs = _load_group_records(paths)
    if not recs:
        return None
    # derive run_dir for OCR per record
    ocr_candidates = []
    for r in recs:
        run_dir = Path(r['__file_path']).parent
        ocr_candidates.append(_extract_ocr_sidecar(run_dir))
    # choose baseline
    baseline = _choose_baseline(recs)
    # pick first meaningful OCR
    ocr_use = None
    for oc in ocr_candidates:
        if _should_ocr_merge(oc):
            ocr_use = oc
            break
    if not ocr_use:
        # No merge needed; baseline is enriched-by-default
        enriched = baseline.copy()
    else:
        key = _sig(baseline, ocr_use)
        if key in merge_cache:
            enriched = merge_cache[key]
        else:
            if _OPENAI_AVAILABLE and can_make_call():
                messages = [
                    {"role": "system", "content": "You output STRICT JSON only."},
                    {"role": "user", "content": [{"type": "text", "text": _merge_prompt(baseline, ocr_use)}]},
                ]
                try:
                    resp = _llm_chat_create(messages=messages, model=EVENT_MERGE_MODEL)
                    try:
                        usage = getattr(resp, 'usage', None)
                        if usage is not None:
                            _TOKEN_COUNTS['merge']['prompt'] += int(getattr(usage, 'prompt_tokens', 0) or 0)
                            _TOKEN_COUNTS['merge']['completion'] += int(getattr(usage, 'completion_tokens', 0) or 0)
                            print(f"[tokens] model={EVENT_MERGE_MODEL} tier={SERVICE_TIER} prompt={int(getattr(usage,'prompt_tokens',0) or 0)} completion={int(getattr(usage,'completion_tokens',0) or 0)} total={int(getattr(usage,'prompt_tokens',0) or 0)+int(getattr(usage,'completion_tokens',0) or 0)}")
                    except Exception:
                        pass
                    try:
                        record_call(1)
                    except Exception:
                        pass
                    enriched = json.loads(resp.choices[0].message.content.strip())
                except Exception:
                    # fallback: deterministic union of a few known fields
                    enriched = _deterministic_merge(baseline, ocr_use)
            else:
                enriched = _deterministic_merge(baseline, ocr_use)
            # normalize any file paths before caching/writing
            enriched = _normalize_repo_relative_paths(enriched)
            merge_cache[key] = enriched
    # write
    if not dry_run:
        ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
        outp = ENRICHED_DIR / f"{eid}.json"
        with open(outp, 'w', encoding='utf-8') as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)
    return enriched


def _deterministic_merge(base: dict, ocr: dict) -> dict:
    out = json.loads(json.dumps(base))  # deep-ish copy
    # merge derived_metrics, events/event_chain, photo/video urls if present in ocr
    def list_union(a, b):
        aa = a if isinstance(a, list) else []
        bb = b if isinstance(b, list) else []
        seen = set()
        res = []
        for x in aa + bb:
            key = json.dumps(x, sort_keys=True, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x)
            if key not in seen:
                seen.add(key)
                res.append(x)
        return res

    for k in ['derived_metrics', 'activity_specific', 'cause_layers']:
        if isinstance(ocr.get(k), dict):
            out[k] = {**out.get(k, {}), **ocr[k]}
    for k in ['events', 'event_chain', 'photo_urls', 'video_urls']:
        if ocr.get(k):
            out[k] = list_union(out.get(k), ocr.get(k))
    return out


def fuse_event(eid: str, enriched: dict, recs: List[dict], dry_run: bool, fuse_cache: Dict[str, Any]) -> dict:
    # Gather all per-source enriched baselines: use enriched + remainder (excluding baseline already included)
    candidates: List[dict] = [enriched]
    for r in recs:
        candidates.append(r)
    # Deterministic pre-fuse
    fused = _deterministic_fuse(candidates)
    # Heuristic: detect conflicts (e.g., different timeline_text or accident_summary_text)
    conflict = _has_conflicts(candidates)
    if conflict and _OPENAI_AVAILABLE and can_make_call():
        key = _sig(candidates)
        if key in fuse_cache:
            fused = fuse_cache[key]
        else:
            messages = [
                {"role": "system", "content": "You output STRICT JSON only."},
                {"role": "user", "content": [{"type": "text", "text": _fuse_prompt(candidates)}]},
            ]
            try:
                resp = _llm_chat_create(messages=messages, model=EVENT_FUSION_MODEL)
                try:
                    usage = getattr(resp, 'usage', None)
                    if usage is not None:
                        _TOKEN_COUNTS['fusion']['prompt'] += int(getattr(usage, 'prompt_tokens', 0) or 0)
                        _TOKEN_COUNTS['fusion']['completion'] += int(getattr(usage, 'completion_tokens', 0) or 0)
                        print(f"[tokens] model={EVENT_FUSION_MODEL} tier={SERVICE_TIER} prompt={int(getattr(usage,'prompt_tokens',0) or 0)} completion={int(getattr(usage,'completion_tokens',0) or 0)} total={int(getattr(usage,'prompt_tokens',0) or 0)+int(getattr(usage,'completion_tokens',0) or 0)}")
                except Exception:
                    pass
                try:
                    record_call(1)
                except Exception:
                    pass
                fused = json.loads(resp.choices[0].message.content.strip())
                fused = _normalize_repo_relative_paths(fused)
                fuse_cache[key] = fused
            except Exception:
                pass
    # Always normalize (covers deterministic path and cache hit as well)
    fused = _normalize_repo_relative_paths(fused)
    if not dry_run:
        FUSED_DIR.mkdir(parents=True, exist_ok=True)
        outp = FUSED_DIR / f"{eid}.json"
        with open(outp, 'w', encoding='utf-8') as f:
            json.dump(fused, f, ensure_ascii=False, indent=2)
    return fused


def _deterministic_fuse(items: List[dict]) -> dict:
    out: dict = {}
    # Sort by confidence score, descending, to prioritize better sources
    items.sort(key=lambda r: float(r.get('extraction_confidence_score', 0) or 0), reverse=True)

    def keep_scalar(k, vals):
        # Intelligent scalar selection based on key
        non_empty_vals = [v for v in vals if v not in (None, "", [], {})]
        if not non_empty_vals:
            return vals[0] if vals else None

        if k in ['accident_summary_text', 'timeline_text']:
            # Prefer the longest, most descriptive text
            return max(non_empty_vals, key=len)
        if k == 'title':
            # Prefer a more descriptive title over a generic one
            return sorted(non_empty_vals, key=lambda t: (isinstance(t, str) and 'None' in t, -len(str(t))))[0]
        if k == 'accident_date':
            # Use the earliest date as the canonical one, but keep others
            try:
                # Filter out invalid date strings before sorting
                valid_dates = sorted([v for v in non_empty_vals if isinstance(v, str) and v.startswith('20')])
                return valid_dates[0] if valid_dates else non_empty_vals[0]
            except Exception:
                return non_empty_vals[0]
        if k == 'extraction_confidence_score':
            # Use the highest confidence score
            return max(non_empty_vals)
        # Default: return the first non-empty value from the highest-confidence source
        return non_empty_vals[0]

    def list_union(vals):
        res = []
        seen = set()
        for arr in vals:
            if not isinstance(arr, list):
                continue
            for x in arr:
                key = json.dumps(x, sort_keys=True, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x)
                if key not in seen:
                    seen.add(key)
                    res.append(x)
        return res
    # Aggregate keys across items
    all_keys = set()
    for it in items:
        all_keys.update(it.keys())
    # Ensure a consistent field order in the output
    sorted_keys = sorted(list(all_keys))

    for k in sorted_keys:
        vals = [it.get(k) for it in items if k in it]
        if any(isinstance(v, list) for v in vals):
            out[k] = list_union(vals)
        elif any(isinstance(v, dict) for v in vals):
            merged = {}
            for v in vals:
                if isinstance(v, dict):
                    merged.update(v)
            out[k] = merged
        else:
            out[k] = keep_scalar(k, vals)

    # Always union source_url to track all original reports
    out['source_url'] = list_union([it.get('source_url') for it in items])

    return out


def _has_conflicts(items: List[dict]) -> bool:
    # Simple conflict detection on a few fields likely to differ
    fields = ['timeline_text', 'accident_summary_text']
    for k in fields:
        vals = [it.get(k) for it in items if k in it and it.get(k)]
        if len(set(vals)) > 1:
            return True
    return False


def run_merge_and_fusion(dry_run: bool = False, cache_clear: bool = False) -> dict:
    paths = _iter_accident_jsons(ARTIFACTS_DIR)
    groups = _group_by_event_id(paths)
    if not groups:
        logger.info("No event_id groups found; ensure event_id_service has been run.")
        return {"events": 0, "enriched": 0, "fused": 0}

    merge_cache = {} if cache_clear else _cache_load(ENRICH_CACHE)
    fuse_cache = {} if cache_clear else _cache_load(FUSE_CACHE)

    enriched_count = 0
    fused_count = 0
    for eid, gpaths in groups.items():
        # Skip event if fused output already exists and is newer than inputs (no-op)
        fused_path = FUSED_DIR / f"{eid}.json"
        if fused_path.exists() and not cache_clear:
            try:
                fused_mtime = fused_path.stat().st_mtime
                latest_input = max((p.stat().st_mtime for p in gpaths), default=0)
                if fused_mtime >= latest_input:
                    # nothing to do for this event
                    continue
            except Exception:
                pass
        enriched = merge_event(eid, gpaths, dry_run, merge_cache)
        if enriched:
            enriched_count += 1
            recs = _load_group_records(gpaths)
            fused = fuse_event(eid, enriched, recs, dry_run, fuse_cache)
            if fused:
                fused_count += 1

    if not dry_run:
        _cache_save(ENRICH_CACHE, merge_cache)
        _cache_save(FUSE_CACHE, fuse_cache)
    return {"events": len(groups), "enriched": enriched_count, "fused": fused_count}


if __name__ == '__main__':
    import argparse
    _TOKEN_COUNTS = {'merge': {'prompt': 0, 'completion': 0}, 'fusion': {'prompt': 0, 'completion': 0}}
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='Merge text+OCR per event and fuse multi-source events into canonical JSONs.')
    parser.add_argument('--dry-run', action='store_true', help='Compute and print results but do not write back to files')
    parser.add_argument('--cache-clear', action='store_true', help='Clear merge/fusion caches and recompute')
    args = parser.parse_args()

    stats = run_merge_and_fusion(dry_run=args.dry_run, cache_clear=args.cache_clear)
    print(f"✅ Merge+Fusion complete over {stats['events']} events. Enriched: {stats['enriched']}, Fused: {stats['fused']}{' (dry-run)' if args.dry_run else ''}.")
    m_p = _TOKEN_COUNTS['merge']['prompt']; m_c = _TOKEN_COUNTS['merge']['completion']
    f_p = _TOKEN_COUNTS['fusion']['prompt']; f_c = _TOKEN_COUNTS['fusion']['completion']
    print(f"[models] merge={EVENT_MERGE_MODEL}, fusion={EVENT_FUSION_MODEL}, tier={SERVICE_TIER}")
    print(f"[tokens] merge prompt={m_p}, completion={m_c}, total={m_p+m_c}; fusion prompt={f_p}, completion={f_c}, total={f_p+f_c}")
