from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from pathlib import Path
from typing import Optional

try:
    from config import TIMEZONE
except Exception:
    TIMEZONE = 'America/Vancouver'


def now_pst_iso() -> str:
    """Return current time formatted in configured TIMEZONE (America/Vancouver) as ISO string (seconds precision)."""
    try:
        if ZoneInfo is not None and TIMEZONE:
            return datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec='seconds')
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat(timespec='seconds') + 'Z'


def now_pst_filename_ts() -> str:
    """Return a filesystem-safe timestamp string (YYYYmmdd_HHMMSS) in the configured timezone."""
    try:
        if ZoneInfo is not None and TIMEZONE:
            return datetime.now(ZoneInfo(TIMEZONE)).strftime('%Y%m%d_%H%M%S')
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
