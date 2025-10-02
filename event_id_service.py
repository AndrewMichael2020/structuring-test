#!/usr/bin/env python3
"""Event ID assignment service.

Scans artifacts/**/accident_info.json, clusters related incidents using an LLM
(gpt-5-mini by default) with caching, assigns a stable event_id for each
cluster, and writes the IDs back to the JSON files.

Usage:
    python event_id_service.py               # assign IDs and write back
    python event_id_service.py --dry-run     # compute, print summary, no writes
    python event_id_service.py --cache-clear # clear cache and recompute

Design notes:
 - Uses optional OpenAI client from accident_llm; falls back to deterministic
   clustering by (mountain_name, accident_date) when LLM unavailable or capped.
 - Cache key accounts for record content signatures so edits invalidate cache.
 - Writes event_id back into each accident_info.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from accident_llm import _chat_create as _llm_chat_create, _OPENAI_AVAILABLE, _supports_temperature
from openai_call_manager import can_make_call, record_call

# Best-effort .env loading like other modules
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


# Configuration
BASE_DIR = Path(__file__).parent
ARTIFACTS_DIR = BASE_DIR / 'artifacts'
CACHE_PATH = BASE_DIR / 'event_cluster_cache.json'

try:
    # Optional override via config.json
    from config import EVENT_CLUSTER_MODEL  # type: ignore
except Exception:
    EVENT_CLUSTER_MODEL = 'gpt-5-mini'


def _iter_accident_jsons(root: Path) -> List[Path]:
    return [
        p for p in root.rglob('accident_info.json')
        if p.is_file()
    ]


def _sig_for_record(rec: dict, path: Path) -> str:
    # Use key fields to construct a content signature
    title = (rec.get('article_title') or '').strip()
    date = (rec.get('accident_date') or rec.get('article_date_published') or '').strip()
    mountain = (rec.get('mountain_name') or '').strip()
    region = (rec.get('region') or '').strip()
    text = (rec.get('article_text') or rec.get('scraped_full_text') or '')[:200].strip()
    seed = f"{path}|{title}|{date}|{mountain}|{region}|{text}"
    return hashlib.md5(seed.encode('utf-8')).hexdigest()


def load_records(paths: List[Path]) -> List[dict]:
    records: List[dict] = []
    for p in paths:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['__file_path'] = str(p)
            data['__sig'] = _sig_for_record(data, p)
            records.append(data)
        except Exception as e:
            logger.warning(f"Failed to load {p}: {e}")
    return records


def build_grouping_batch(records: List[dict]) -> List[dict]:
    batch = []
    for i, r in enumerate(records):
        batch.append({
            'index': i,
            'title': r.get('article_title'),
            'date': r.get('accident_date') or r.get('article_date_published'),
            'mountain': r.get('mountain_name'),
            'region': r.get('region'),
            'source_url': r.get('source_url'),
            'excerpt': (r.get('article_text') or r.get('scraped_full_text') or '')[:600],
        })
    return batch


def make_cache_key(records: List[dict]) -> str:
    sigs = sorted(r.get('__sig', '') for r in records)
    return hashlib.md5('|'.join(sigs).encode('utf-8')).hexdigest()


def load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Any]):
    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cluster_prompt(records: List[dict]) -> str:
    return (
        "Group the following mountain accident news records into clusters, where each cluster "
        "represents the same real-world event. Return VALID JSON array like: "
        "[{\"cluster_id\":0,\"indices\":[0,2]},{\"cluster_id\":1,\"indices\":[1]}].\n\n"
        f"Records:\n{json.dumps(build_grouping_batch(records), ensure_ascii=False)}\n"
        "Guidance: Prefer matching by (date ±1 day), mountain/region names (or aliases), and title similarity."
    )


def cluster_with_llm(records: List[dict]) -> List[dict] | None:
    if not _OPENAI_AVAILABLE or not can_make_call():
        return None
    messages = [
        {"role": "system", "content": "You are a clustering assistant that outputs STRICT JSON only."},
        {"role": "user", "content": [{"type": "text", "text": _cluster_prompt(records)}]},
    ]
    try:
        resp = _llm_chat_create(messages=messages, model=EVENT_CLUSTER_MODEL)
        try:
            record_call(1)
        except Exception:
            pass
        content = resp.choices[0].message.content.strip()
        clusters = json.loads(content)
        if isinstance(clusters, list):
            # basic validation
            out = []
            for c in clusters:
                if isinstance(c, dict) and 'indices' in c and isinstance(c['indices'], list):
                    out.append({'cluster_id': c.get('cluster_id', len(out)), 'indices': [int(i) for i in c['indices'] if isinstance(i, (int, float))]})
            return out
    except Exception as e:
        logger.warning(f"LLM clustering failed: {e}")
        return None
    return None


def cluster_deterministic(records: List[dict]) -> List[dict]:
    # Fallback: cluster by (mountain_name, accident_date) else source_url seed
    groups: Dict[str, List[int]] = {}
    for i, r in enumerate(records):
        date = (r.get('accident_date') or r.get('article_date_published') or '').strip()
        mt = (r.get('mountain_name') or '').strip().lower()
        if date and mt:
            key = f"{mt}|{date}"
        else:
            seed = (r.get('source_url') or r.get('article_title') or str(r.get('__file_path')))
            key = hashlib.md5(seed.encode('utf-8')).hexdigest()[:16]
        groups.setdefault(key, []).append(i)
    clusters = []
    cid = 0
    for _, idxs in groups.items():
        clusters.append({"cluster_id": cid, "indices": idxs})
        cid += 1
    return clusters


def assign_event_ids(records: List[dict], clusters: List[dict]) -> None:
    for c in clusters:
        if not c.get('indices'):
            continue
        first = records[c['indices'][0]]
        seed = (first.get('mountain_name') or '').strip() + '|' + (first.get('accident_date') or first.get('article_date_published') or '').strip()
        if not seed.strip():
            # fallback seeds
            seed = (first.get('article_title') or first.get('source_url') or first.get('__file_path') or '')
        event_id = hashlib.md5(seed.encode('utf-8')).hexdigest()[:12]
        for idx in c['indices']:
            records[idx]['event_id'] = event_id


def write_event_ids(records: List[dict], dry_run: bool = False) -> int:
    wrote = 0
    for r in records:
        eid = r.get('event_id')
        path = r.get('__file_path')
        if not eid or not path:
            continue
        if dry_run:
            wrote += 1
            continue
        try:
            p = Path(path)
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['event_id'] = eid
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            wrote += 1
        except Exception as e:
            logger.warning(f"Failed to write event_id to {path}: {e}")
    return wrote


def assign_ids_over_artifacts(dry_run: bool = False, cache_clear: bool = False) -> dict:
    paths = _iter_accident_jsons(ARTIFACTS_DIR)
    if not paths:
        logger.info("No accident_info.json files found under artifacts/")
        return {"files": 0, "clusters": 0, "written": 0}
    records = load_records(paths)
    cache = {} if cache_clear else load_cache()
    key = make_cache_key(records)

    if key in cache:
        clusters = cache[key]
    else:
        clusters = cluster_with_llm(records)
        if clusters is None:
            clusters = cluster_deterministic(records)
        cache[key] = clusters
        save_cache(cache)

    assign_event_ids(records, clusters)
    written = write_event_ids(records, dry_run=dry_run)
    return {"files": len(records), "clusters": len(clusters), "written": written}


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='Assign stable event IDs to accident JSONs by clustering related articles.')
    parser.add_argument('--dry-run', action='store_true', help='Compute and print results but do not write back to files')
    parser.add_argument('--cache-clear', action='store_true', help='Clear cluster cache and recompute')
    args = parser.parse_args()

    stats = assign_ids_over_artifacts(dry_run=args.dry_run, cache_clear=args.cache_clear)
    print(f"✅ Assigned event IDs over {stats['files']} files across {stats['clusters']} clusters. Written: {stats['written']}{' (dry-run)' if args.dry_run else ''}.")
