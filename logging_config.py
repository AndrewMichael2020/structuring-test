import logging
import os


def configure_logging(level: str | None = None) -> None:
    """Configure default root logging only if not already configured.

    This helper respects the LOG_LEVEL environment variable and any explicit
    `level` argument. It calls basicConfig only when the root logger has no
    handlers, otherwise it only sets the root level. This avoids double-
    configuring logging when running under test harnesses.
    """
    chosen = (os.getenv("LOG_LEVEL") or level or "INFO").upper()
    lvl = getattr(logging, chosen, logging.INFO)
    root = logging.getLogger()

    if not root.handlers:
        logging.basicConfig(
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=lvl,
        )
    else:
        root.setLevel(lvl)
