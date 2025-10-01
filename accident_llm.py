"""LLM client and extraction function for accident info."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from accident_schema import _SCHEMA_TEXT, _PROMPT
from accident_preextract import pre_extract_fields
from config import ACCIDENT_INFO_MODEL
from openai_call_manager import can_make_call, record_call

logger = logging.getLogger(__name__)
try:
    logger.addHandler(logging.NullHandler())
except Exception:
    pass


# Load .env if available (best-effort)
try:
    from dotenv import load_dotenv  # type: ignore
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    else:
        load_dotenv(override=False)
except Exception:
    pass


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


def _supports_temperature(model_name: str) -> bool:
    try:
        mn = (model_name or '').lower()
        if mn.startswith('gpt-5'):
            return False
        return True
    except Exception:
        return True


def _chat_create(messages: list, model: str):
    kwargs = {'model': model, 'messages': messages}
    if _supports_temperature(model):
        kwargs['temperature'] = 0
    return _client.chat.completions.create(**kwargs)


def llm_extract(article_text: str) -> dict:
    """Run the main extraction prompt; returns a dict or {} on failure."""
    content = article_text[:18000]
    pre = pre_extract_fields(article_text)
    if not _OPENAI_AVAILABLE or _client is None:
        logger.warning("OPENAI_API_KEY not set; skipping LLM extraction")
        return {}
    if not can_make_call():
        logger.warning("OpenAI call cap reached (remaining=0); skipping LLM extraction")
        return {}

    prompt = _PROMPT.format(
        SCHEMA=_SCHEMA_TEXT,
        PRE=json.dumps(pre, ensure_ascii=False, indent=2),
        ARTICLE=content,
    )
    resp = _chat_create(
        messages=[
            {"role": "system", "content": "You are a precise JSON-only extractor."},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        model=ACCIDENT_INFO_MODEL,
    )
    try:
        record_call(1)
    except Exception:
        pass
    raw = resp.choices[0].message.content.strip()

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    repair = _chat_create(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Convert the following to STRICT JSON only, no explanations:\n"
                            + raw
                        ),
                    }
                ],
            }
        ],
        model=ACCIDENT_INFO_MODEL,
    )
    try:
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


__all__ = [
    "llm_extract",
    "_chat_create",
    "_supports_temperature",
    "_OPENAI_AVAILABLE",
]
