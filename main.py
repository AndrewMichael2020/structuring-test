#!/usr/bin/env python3
"""
main.py
Orchestrates full pipeline:
1. Extract captions + download images → JSON
2. Run OCR condition analysis on images → enrich JSON
"""

import sys
import os
import argparse
import logging
from typing import List
from extract_captions import extract_and_save
from image_ocr import enrich_json_with_conditions
from pathlib import Path
from accident_info import extract_accident_info, batch_extract_accident_info
from urllib.parse import urlparse
from store_artifacts import force_rebuild_and_upload_artifacts_csv
from logging_config import configure_logging

# configure module-level logger; main() will configure root logging
logger = logging.getLogger(__name__)


def ts_print(*args, level: str = 'info', **kwargs):
    """Compatibility wrapper used across the CLI to print timestamped messages.

    It forwards messages to the logging system so verbosity can be controlled centrally.
    """
    msg = " ".join(str(a) for a in args)
    lvl = level.lower()
    if lvl == 'debug':
        logger.debug(msg, **kwargs)
    elif lvl == 'warning' or lvl == 'warn':
        logger.warning(msg, **kwargs)
    elif lvl == 'error':
        logger.error(msg, **kwargs)
    else:
        logger.info(msg, **kwargs)

if __name__ == "__main__":
    # Configure logging via helper (only sets defaults if not already configured).
    configure_logging()
    parser = argparse.ArgumentParser(description='Extract accident info from news URLs')
    parser.add_argument('urls', nargs='*', help='One or more URLs to process')
    parser.add_argument('--mode', choices=['all', 'text-only', 'ocr-only'], default='all',
                        help='Run mode: all, text-only, or ocr-only (default: all)')
    parser.add_argument('--urls-file', type=str, default=None,
                        help='Path to a file with URLs (one per line) to run in batched LLM mode')
    parser.add_argument('--batch-size', type=int, default=3, help='Number of URLs per LLM batch')
    parser.add_argument('--write-drive', action='store_true', help='Upload artifacts CSV and JSON to Google Drive (requires Drive env vars and auth)')
    args = parser.parse_args()

    urls: List[str] = []
    if args.urls_file:
        p = Path(args.urls_file)
        if not p.exists():
            ts_print(f'URLs file not found: {args.urls_file}')
            sys.exit(1)
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                # Support comma-separated lists per line as well as one-per-line
                parts = [x.strip() for x in s.split(',')]
                for part in parts:
                    if part:
                        urls.append(part)
    elif not args.urls:
        # interactive single URL prompt
        u = input('Enter a URL: ').strip()
        urls = [u]
    else:
        urls = args.urls

    mode = args.mode
    if mode not in ('all', 'text-only', 'ocr-only'):
        # interactive selection
        ts_print("Select run mode:")
        ts_print("  1) all (extract images, OCR, and article text)")
        ts_print("  2) text-only (skip OCR & image downloads, only extract article text)")
        ts_print("  3) ocr-only (use existing captions.json if present; run OCR only)")
        choice = input("Enter choice [1/2/3]: ").strip()
        if choice == '2':
            mode = 'text-only'
        elif choice == '3':
            mode = 'ocr-only'
        else:
            mode = 'all'

    ts_print(f"[INFO] Running mode: {mode}")

    # Enable Drive sync when requested via CLI flag
    if args.write_drive or os.getenv('WRITE_TO_DRIVE', '').lower() in ('1', 'true', 'yes'):
        os.environ['WRITE_TO_DRIVE'] = 'true'

    # If urls-file was provided, run batch LLM extraction (text-only behavior for batched LLM)
    if args.urls_file:
        # ensure DRIVE writing is enabled for batched mode when requested
        if args.write_drive:
            os.environ['WRITE_TO_DRIVE'] = 'true'
        ts_print(f'[INFO] Running batched extraction for {len(urls)} URLs with batch size {args.batch_size}')
        written = batch_extract_accident_info(urls, batch_size=args.batch_size)
        ts_print(f'[INFO] Wrote {len(written)} artifacts')
        for p in written[:10]:
            ts_print(' -', p)
        sys.exit(0)

    # Otherwise run per-URL behavior
    for url in urls:
        json_path = None
        run_dir = None
        if mode == 'ocr-only':
            base = Path('artifacts') / Path(urlparse(url).netloc.replace('www.', ''))
            if not base.exists():
                ts_print(f"No artifacts found for {url}; nothing to OCR")
                continue
            runs = sorted([p for p in base.iterdir() if p.is_dir()])
            if not runs:
                ts_print(f"No runs found in {base}; nothing to OCR")
                continue
            latest = runs[-1]
            json_path = str(latest / 'captions.json')
            run_dir = str(latest)
            ts_print(f"Using existing captions.json: {json_path}")
            enrich_json_with_conditions(json_path)

        elif mode == 'text-only':
            json_path = extract_and_save(url, run_ocr=False, download_images=False)
            run_dir = str(Path(json_path).parent)
            ts_print(f"[INFO] Extracting accident info for {url}")
            extract_accident_info(url, out_dir=run_dir)
            # Always force CSV rebuild and Drive upload after extraction
            force_rebuild_and_upload_artifacts_csv()

        else:  # all
            json_path = extract_and_save(url, run_ocr=True, download_images=True)
            ts_print(f"[INFO] Extracting HTML captions from {url}")
            enrich_json_with_conditions(json_path)
            run_dir = str(Path(json_path).parent)
            ts_print(f"[INFO] Extracting accident info for {url}")
            extract_accident_info(url, out_dir=run_dir)
            # Always force CSV rebuild and Drive upload after extraction
            force_rebuild_and_upload_artifacts_csv()
