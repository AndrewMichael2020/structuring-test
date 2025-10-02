"""Simple in-memory token usage tracker for the current CLI run.

Other modules report token usage here so `main.py` can print a single summary
at the end of execution.
"""
from threading import Lock

_LOCK = Lock()
_TOTAL = { 'prompt': 0, 'completion': 0 }

def add_usage(prompt_tokens: int, completion_tokens: int):
    with _LOCK:
        _TOTAL['prompt'] += int(prompt_tokens or 0)
        _TOTAL['completion'] += int(completion_tokens or 0)

def summary() -> dict:
    with _LOCK:
        p = int(_TOTAL['prompt'])
        c = int(_TOTAL['completion'])
        return {'prompt': p, 'completion': c, 'total': p + c}

def reset():
    with _LOCK:
        _TOTAL['prompt'] = 0
        _TOTAL['completion'] = 0
