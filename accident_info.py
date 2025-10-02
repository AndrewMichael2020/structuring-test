#!/usr/bin/env python3
"""
accident_info.py

Page-level accident metadata extraction using an OpenAI model configured
via config (ACCIDENT_INFO_MODEL).

- Fetches page HTML and extracts main article text (robust selectors +
  fallback).
- Asks a model like GPT-5 to return STRICT JSON with only present fields.
- Validates and normalizes dates to ISO (YYYY-MM-DD) when possible.
- Writes artifacts/<domain>/<timestamp>/accident_info.json unless out_dir is
  provided.

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
from urllib.parse import urlparse
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from pathlib import Path
import logging

# Attempt to load a .env file in the project directory so os.getenv sees
# local keys (e.g., OPENAI_API_KEY)
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
    # If python-dotenv isn't installed, try a minimal manual parse of a .env
    # file so local development still works without the dependency.
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

from config import ACCIDENT_INFO_MODEL, SERVICE_TIER
from accident_schema import _SCHEMA_TEXT
try:
    try:
    # prefer the DB upsert when available, but also expose a Drive-only
    # sync helper
        from store_artifacts import upsert_artifact, init_db, sync_artifact_to_drive
    except Exception:
        upsert_artifact = None
        init_db = None
        sync_artifact_to_drive = None
except Exception:
    upsert_artifact = None
    init_db = None
from openai_call_manager import can_make_call, record_call
from time_utils import now_pst_iso

# Toggle whether to inject a small stealth/init script into Playwright
# contexts. Set PLAYWRIGHT_STEALTH=0/false to disable if it causes
# compatibility issues.
PLAYWRIGHT_STEALTH = os.getenv("PLAYWRIGHT_STEALTH", "true").lower() in (
    "1", "true", "yes"
)

from accident_utils import _ensure_outdir, _slugify
from accident_preextract import pre_extract_fields
from accident_postprocess import _postprocess, compute_confidence
from accident_llm import llm_extract, _OPENAI_AVAILABLE
import accident_llm as _al

# Local client shim for tests; batch path uses this _client via _chat_create
_client = None

def _supports_temperature(model_name: str) -> bool:
    try:
        mn = (model_name or '').lower()
        return not mn.startswith('gpt-5')
    except Exception:
        return True

def _chat_create(messages: list, model: str):
    """Create a chat completion for batch mode.

    Behavior:
    - If tests have patched this module's _client, use it (preserves unit test hooks).
    - Otherwise, delegate to the shared accident_llm._chat_create which uses the real OpenAI client when configured.
    """
    kwargs = {'model': model, 'messages': messages}
    if _supports_temperature(model):
        kwargs['temperature'] = 0
    if _client is not None:
        resp = _client.chat.completions.create(**kwargs)
        try:
            usage = getattr(resp, 'usage', None)
            if usage is not None:
                pt = int(getattr(usage, 'prompt_tokens', 0) or 0)
                ct = int(getattr(usage, 'completion_tokens', 0) or 0)
                print(f"[tokens] model={model} tier={SERVICE_TIER} prompt={pt} completion={ct} total={pt+ct}")
        except Exception:
            pass
        return resp
    # delegate to shared LLM client (returns an OpenAI response object)
    return _al._chat_create(messages=messages, model=model)


# use centralized timezone helpers in `time_utils.py`


# pre-extraction is provided by accident_preextract.pre_extract_fields

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


"""
# LLM schema/prompt and extraction moved to modules.
"""


# post-processing and confidence are provided by accident_postprocess


# -------------------- public API --------------------

def extract_accident_info(
    url: str,
    out_dir: str | Path | None = None,
    base_output: str = "artifacts",
) -> str:
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
    # Ensure Playwright nav timeout is capped at 25s via env var handling
    try:
        os.environ['PLAYWRIGHT_NAV_TIMEOUT_MS'] = str(
            min(int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS', '25000')), 25000)
        )
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
    obj = llm_extract(text)
    # attach the pre-extracted dict into the object for downstream use
    if isinstance(obj, dict):
        obj['gazetteer_matches'] = pre.get('gazetteer_matches', [])
    info = _postprocess(obj)

    # compute deterministic confidence and prefer it if model did not provide one
    try:
        if (
            'extraction_confidence_score' not in info
            or not isinstance(
                info.get('extraction_confidence_score'), float
            )
        ):
            c = compute_confidence(pre, info)
            info['extraction_confidence_score'] = c
        else:
            # combine model score and deterministic score conservatively
            model_score = float(info.get('extraction_confidence_score'))
            det = compute_confidence(pre, info)
            # weighted average favoring deterministic evidence slightly
            info['extraction_confidence_score'] = round(
                (0.4 * model_score + 0.6 * det), 2
            )
    except Exception:
        pass

    # attach minimal source context and include the cleaned article text for
    # traceability; include both the focused article_text and the full scraped
    # text (before trimming). Build payload but ensure the canonical URL passed
    # to the function wins
    payload = {
        "extracted_at": now_pst_iso(),
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
        # WRITE_TO_DB: legacy behaviour to persist into sqlite DB
        if (
            os.getenv('WRITE_TO_DB', 'false').lower() in ('1', 'true', 'yes')
            and upsert_artifact is not None
        ):
            try:
                init_db() if init_db is not None else None
            except Exception:
                pass
            try:
                upsert_artifact(payload)
            except Exception as e:
                logger.warning(f"Failed to write artifact to DB: {e}")

        # WRITE_TO_DRIVE: opt-in shorthand to write CSV + upload to Drive without using sqlite
        if (
            os.getenv('WRITE_TO_DRIVE', 'false').lower() in ('1', 'true', 'yes')
            and sync_artifact_to_drive is not None
        ):
            try:
                sync_artifact_to_drive(payload)
            except Exception as e:
                logger.warning(f"Failed to sync artifact to Drive: {e}")
    except Exception:
        pass

    logger.info(f"✅ Wrote {json_path}")
    return json_path


def batch_extract_accident_info(
    urls: list[str],
    batch_size: int = 3,
    base_output: str = "artifacts",
) -> list[str]:
    """Process a list of URLs in batches. For each batch we perform
    deterministic pre-extraction and then make a single LLM call that returns
    a JSON array of extraction objects. We then postprocess and write per-URL
    `accident_info.json` files under artifacts.

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
                od = (
                    Path(base_output)
                    / _slugify(urlparse(u).netloc.replace('www.', ''))
                    / datetime.now().strftime('%Y%m%d_%H%M%S')
                )
                od.mkdir(parents=True, exist_ok=True)
            out_dirs.append(od)
            # extract text deterministically; accept either (full, focused)
            # or (full, focused, final_url)
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
        # helper to write a minimal artifact for index idx within this batch
        def _write_minimal(idx: int):
            payload_write = {
                'extracted_at': now_pst_iso(),
                'article_text': texts[idx],
                'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                'pre_extracted': pre_list[idx],
            }
            payload_write['source_url'] = (
                final_urls[idx] if idx < len(final_urls) and final_urls[idx] else batch[idx]
            )
            pth = str(out_dirs[idx] / 'accident_info.json')
            with open(pth, 'w', encoding='utf-8') as f:
                json.dump(payload_write, f, indent=2, ensure_ascii=False)
            written.append(pth)
    # Build a batched prompt asking for an array of JSON objects
        items = []
        for idx, u in enumerate(batch):
            # Provide both focused and full text contexts to the LLM to help when pages are teaser-only
            items.append({
                'url': u,
                'pre_extracted': pre_list[idx],
                'article_focused': texts[idx][:12000],
                'article_full': (full_texts[idx] if idx < len(full_texts) else '')[:16000],
            })

    # Compose prompt: SCHEMA + list of items
        payload = {
            'items': items
        }

        # Respect call caps and availability
        if not _OPENAI_AVAILABLE:
            logger.warning(
                'OPENAI_API_KEY not set; skipping batch LLM extraction'
            )
            # still write minimal artifacts with scraped_full_text and
            # pre_extracted
            for idx, u in enumerate(batch):
                _write_minimal(idx)
            continue

        # check call cap before attempting the batch call
        if not can_make_call():
            logger.warning(
                'OpenAI call cap reached; skipping LLM batch for this group'
            )
            for idx, u in enumerate(batch):
                _write_minimal(idx)
            continue

        # single LLM call for the batch
        # Provide the canonical schema text up-front so the model returns the
        # same STRICT JSON structure as single-item extraction. Include the
        # items payload after the schema to keep the prompt size reasonable.
        prompt = (
            "System: Return a JSON array with one extraction object per item.\n"
            "Follow the SCHEMA below exactly and return only a JSON array.\n\n"
            "SCHEMA:\n" + _SCHEMA_TEXT + "\n\n"
            "Use the provided PRE-EXTRACTED fields plus ARTICLE_FOCUSED and ARTICLE_FULL. "
            "Prefer ARTICLE_FOCUSED when it seems like a cleaned summary; if it's too short or teaser, "
            "supplement with ARTICLE_FULL. Do not hallucinate; only infer cautiously.\n\n"
        )
        prompt += json.dumps(payload, ensure_ascii=False)

        try:
            resp = _chat_create(
                model=ACCIDENT_INFO_MODEL,
                messages=[
                    {
                        'role': 'system',
                        'content': 'You are a precise JSON-only extractor.',
                    },
                    {
                        'role': 'user',
                        'content': [{'type': 'text', 'text': prompt}],
                    },
                ],
            )
        except Exception as e:
            logger.warning(f'Batch LLM call failed: {e}')
            # Write minimal artifacts for each item in this batch
            for idx in range(len(batch)):
                _write_minimal(idx)
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
                repair = _chat_create(
                    model=ACCIDENT_INFO_MODEL,
                    messages=[
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': (
                                        'Convert the following to a JSON '
                                        'array only:\n' + raw
                                    ),
                                }
                            ],
                        }
                    ],
                )
                arr = json.loads(
                    repair.choices[0].message.content.strip()
                )

            # record that we used one LLM call for the batch
            try:
                record_call(1)
            except Exception:
                pass
        except Exception:
            logger.warning('Failed to parse batch LLM response; writing minimal artifacts for batch')
            for idx in range(len(batch)):
                _write_minimal(idx)
            continue

        # postprocess and write per-url artifacts
    # If response length doesn't match batch length, be conservative:
    # iterate up to min length
        min_len = min(len(arr), len(batch))
        if len(arr) != len(batch):
            logger.warning(
                f'LLM returned {len(arr)} items for batch of {len(batch)}; '
                f'aligning to {min_len} items'
            )

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
                'extracted_at': now_pst_iso(),
                'article_text': texts[idx],
                'scraped_full_text': full_texts[idx] if idx < len(full_texts) else '',
                **info
            }
            # Force canonical source_url from the batch URL (prevent LLM
            # override)
            payload_write['source_url'] = batch[idx]
            p = str(out_dirs[idx] / 'accident_info.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(payload_write, f, indent=2, ensure_ascii=False)
            written.append(p)
            # optional DB write for batch items
            try:
                if (
                    os.getenv('WRITE_TO_DB', 'false').lower()
                    in ('1', 'true', 'yes')
                    and upsert_artifact is not None
                ):
                    try:
                        if init_db is not None:
                            init_db()
                    except Exception:
                        pass
                    try:
                        upsert_artifact(payload_write)
                    except Exception as e:
                        logger.warning(
                            f"Failed to write batch artifact to DB: {e}"
                        )
            except Exception:
                pass

        # For any remaining URLs beyond the returned array length, write minimal artifacts
        if len(arr) < len(batch):
            for idx in range(len(arr), len(batch)):
                _write_minimal(idx)

    return written


# -------------------- CLI --------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        logger.info(f"Usage: python {Path(__file__).name} <URL>")
        sys.exit(1)
    extract_accident_info(sys.argv[1])
