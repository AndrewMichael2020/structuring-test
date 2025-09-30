"""Simple persistent OpenAI call counter for per-run caps.

Env:
  MAX_OPENAI_CALLS: integer cap (0 or unset = unlimited)
  OPENAI_CALLS_PATH: path to persist JSON state (default: .openai_calls.json)

Functions:
  can_make_call() -> bool
  record_call() -> None
  remaining() -> int|None
"""
import os
import json
from pathlib import Path
from threading import Lock

_LOCK = Lock()
_PATH = Path(os.getenv('OPENAI_CALLS_PATH', '.openai_calls.json'))
try:
    _CAP = int(os.getenv('MAX_OPENAI_CALLS', '0'))
except Exception:
    _CAP = 0

def _read_state():
    if not _PATH.exists():
        return {'count': 0}
    try:
        with _PATH.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'count': 0}

def _write_state(state: dict):
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with _PATH.open('w', encoding='utf-8') as f:
            json.dump(state, f)
    except Exception:
        pass

def can_make_call() -> bool:
    """Return True if a call may be made under current cap. If cap==0, unlimited."""
    if _CAP <= 0:
        return True
    with _LOCK:
        st = _read_state()
        return int(st.get('count', 0)) < _CAP

def remaining() -> int | None:
    if _CAP <= 0:
        return None
    with _LOCK:
        st = _read_state()
        return max(0, _CAP - int(st.get('count', 0)))

def record_call(n: int = 1) -> None:
    """Increment persisted call count by n."""
    if _CAP <= 0:
        return
    with _LOCK:
        st = _read_state()
        c = int(st.get('count', 0)) + int(n)
        st['count'] = c
        _write_state(st)
