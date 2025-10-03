"""Deterministic LLM extraction stub for tests/CI.

Usage patterns:
  from llm_stub import llm_extract_stub  # then monkeypatch where needed

Rationale: Keep production modules free of test-only environment branching.

You can wire this in tests via:
  monkeypatch.setattr('accident_llm.llm_extract', llm_extract_stub)

Or in CI by setting an env var and having a small conditional import *in test harness only*.

We deliberately mirror a subset of expected keys so downstream code paths behave.
"""
from __future__ import annotations
from typing import Dict, Any
import hashlib

def llm_extract_stub(article_text: str) -> Dict[str, Any]:
    h = hashlib.sha1(article_text.encode('utf-8')).hexdigest()[:8]
    return {
        "stub": True,
        "title": f"Stub Extraction {h}",
        "activity": "unknown",
        "raw_character_count": len(article_text),
        "hash": h,
    }

__all__ = ["llm_extract_stub"]
