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
from event_id_service import assign_ids_over_artifacts as _assign_event_ids
from event_merge_service import run_merge_and_fusion as _merge_and_fuse
from services.report_service import generate_report as _generate_report
from config import SERVICE_TIER
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
    parser = argparse.ArgumentParser(description='Accident pipeline CLI: extract, group events, merge/fuse, and generate reports')
    parser.add_argument('urls', nargs='*', help='One or more URLs to process')
    parser.add_argument('--mode', choices=['all', 'text-only', 'ocr-only'], default='all',
                        help='Run mode: all, text-only, or ocr-only (default: all)')
    parser.add_argument('--urls-file', type=str, default=None,
                        help='Path to a file with URLs (one per line) to run in batched LLM mode')
    parser.add_argument('--batch-size', type=int, default=3, help='Number of URLs per LLM batch')
    parser.add_argument('--write-drive', action='store_true', help='Upload artifacts CSV and JSON to Google Drive (requires Drive env vars and auth)')
    # Service pipeline flags
    parser.add_argument('--assign-event-ids', action='store_true', help='Cluster artifacts and write event_id into accident_info.json files')
    parser.add_argument('--merge-events', action='store_true', help='Merge per-event text+OCR (enriched) and fuse multi-source (fused)')
    parser.add_argument('--generate-reports', action='store_true', help='Generate Markdown reports from fused events')
    parser.add_argument('--dry-run', action='store_true', help='Service actions only: compute but do not write outputs')
    parser.add_argument('--cache-clear', action='store_true', help='Service actions: clear caches and recompute where applicable')
    parser.add_argument('--event-id', type=str, default=None, help='Target a specific event_id when generating reports')
    parser.add_argument('--audience', choices=['climbers','general'], default='climbers', help='Report audience (default: climbers)')
    parser.add_argument('--family-sensitive', action='store_true', help='Enable sensitive tone/redactions for reports')
    parser.add_argument('--service-tier', choices=['standard','flex','batch','priority'], default=None, help='Override SERVICE_TIER for this run')
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
        # Interactive menu when no URLs provided: guide the user through common flows
        if args.assign_event_ids or args.merge_events or args.generate_reports:
            urls = []
        else:
            def _yn(prompt: str, default: bool = True) -> bool:
                d = 'Y/n' if default else 'y/N'
                r = input(f"{prompt} ({d}): ").strip().lower()
                if not r:
                    return default
                return r in ('y','yes')

            print('\nNo URLs provided. Choose an action:')
            print('  1) Process a single URL now (interactive)')
            print('  2) Run batched extraction from a URLs file')
            print('  3) Run service pipeline (assign IDs, merge, generate reports)')
            print('  4) Exit')
            choice = input('Enter choice [1-4]: ').strip()
            if choice == '1':
                u = input('Enter a URL: ').strip()
                if not u:
                    print('No URL entered; exiting.')
                    sys.exit(0)
                # ask mode for this single URL
                m = input('Mode [all/text-only/ocr-only] (default: all): ').strip().lower()
                if m not in ('all','text-only','ocr-only'):
                    m = 'all'
                mode = m
                urls = [u]
            elif choice == '2':
                fp = input('Path to URLs file (default: urls.txt): ').strip() or 'urls.txt'
                p = Path(fp)
                if not p.exists():
                    print(f'URLs file not found: {fp}')
                    sys.exit(1)
                args.urls_file = fp
                bs = input(f'Batch size (default {args.batch_size}): ').strip()
                try:
                    args.batch_size = int(bs) if bs else args.batch_size
                except Exception:
                    pass
                # will flow into the urls_file branch above
                p = Path(args.urls_file)
                with open(p, 'r', encoding='utf-8') as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith('#'):
                            continue
                        parts = [x.strip() for x in s.split(',')]
                        for part in parts:
                            if part:
                                urls.append(part)
            elif choice == '3':
                print('\nService pipeline options:')
                if _yn('Assign event IDs?', default=True):
                    args.assign_event_ids = True
                if _yn('Merge events (enriched/fused)?', default=True):
                    args.merge_events = True
                if _yn('Generate reports?', default=False):
                    args.generate_reports = True
                    eid = input('Target event_id (leave empty for all): ').strip()
                    if eid:
                        args.event_id = eid
                    aud = input('Audience [climbers/general] (default climbers): ').strip().lower()
                    if aud in ('climbers','general'):
                        args.audience = aud
                    if _yn('Family-sensitive tone?', default=True):
                        args.family_sensitive = True
                if _yn('Dry run (do not write outputs)?', default=True):
                    args.dry_run = True
                if _yn('Clear caches before compute?', default=False):
                    args.cache_clear = True
                urls = []
            else:
                print('Exiting.')
                sys.exit(0)
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

    # Handle service tier override
    if args.service_tier:
        os.environ['SERVICE_TIER'] = args.service_tier
        ts_print(f"[INFO] Using service_tier override: {args.service_tier}")
    else:
        ts_print(f"[INFO] Using service_tier: {SERVICE_TIER}")

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
        # After batched extraction, propose the service pipeline unless flags were provided.
        if not (args.assign_event_ids or args.merge_events or args.generate_reports):
            def _yn(prompt: str, default: bool = True) -> bool:
                d = 'Y/n' if default else 'y/N'
                r = input(f"{prompt} ({d}): ").strip().lower()
                if not r:
                    return default
                return r in ('y','yes')

            print('\nBatched artifact processing complete')
            if _yn('Run the service pipeline now (assign IDs, merge, generate reports)?', default=True):
                dry = _yn('Dry run (compute only, do not write outputs)?', default=True)
                clear = _yn('Clear caches before compute?', default=False)
                run_assign = _yn('Assign event IDs?', default=True)
                run_merge = _yn('Merge events (enriched/fused)?', default=True)
                run_reports = _yn('Generate reports?', default=False)
                report_eid = None
                report_aud = args.audience
                report_family = args.family_sensitive
                if run_reports:
                    eid_in = input('Target event_id (leave empty for all): ').strip()
                    if eid_in:
                        report_eid = eid_in
                    aud_in = input(f"Audience [climbers/general] (default: {args.audience}): ").strip().lower()
                    if aud_in in ('climbers','general'):
                        report_aud = aud_in
                    if _yn('Family-sensitive tone?', default=args.family_sensitive):
                        report_family = True

                ts_print('[INFO] Running selected service pipeline steps...')
                if run_assign:
                    stats = _assign_event_ids(dry_run=dry, cache_clear=clear)
                    ts_print(f"[service] event_id assignment: files={stats.get('files',0)} clusters={stats.get('clusters',0)} written={stats.get('written',0)}{' (dry-run)' if dry else ''}")
                if run_merge:
                    stats = _merge_and_fuse(dry_run=dry, cache_clear=clear)
                    ts_print(f"[service] merge+fusion: events={stats.get('events',0)} enriched={stats.get('enriched',0)} fused={stats.get('fused',0)}{' (dry-run)' if dry else ''}")
                    ts_print('[note] Fused outputs are canonical: events/fused/{event_id}.json')
                if run_reports:
                    from pathlib import Path as _P
                    fused_dir = _P('events') / 'fused'
                    if report_eid:
                        targets = [report_eid]
                    else:
                        targets = [p.stem for p in fused_dir.glob('*.json')]
                    wrote = 0
                    for eid in targets:
                        pth = _generate_report(eid, audience=report_aud, family_sensitive=report_family, dry_run=dry)
                        if pth:
                            wrote += 1
                            ts_print(f"[report] wrote {pth}")
                    ts_print(f"[service] reports: {wrote}/{len(targets)} written{' (dry-run)' if dry else ''}")
        # exit after batch flow
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
            # New order: extract and analyze text first; skip image/OCR tasks
            ts_print(f"[INFO] Extracting accident info for {url}")
            extract_accident_info(url)
            # Always force CSV rebuild and Drive upload after extraction
            force_rebuild_and_upload_artifacts_csv()

        else:  # all
            # New order: extract and analyze text first, then run image/OCR tasks
            ts_print(f"[INFO] Extracting accident info for {url}")
            extract_accident_info(url)
            # Then extract captions/images and perform OCR enrichment
            json_path = extract_and_save(url, run_ocr=True, download_images=True)
            ts_print(f"[INFO] Enriching image captions with OCR/Vision for {url}")
            enrich_json_with_conditions(json_path)
            # Always force CSV rebuild and Drive upload after extraction
            force_rebuild_and_upload_artifacts_csv()

        # After artifact-level work, if the user didn't already request service flags,
        # propose next steps (assign IDs, merge, generate reports) interactively.
        # This helps the CLI drive the full pipeline without requiring flags up-front.
        if not (args.assign_event_ids or args.merge_events or args.generate_reports):
            def _yn(prompt: str, default: bool = True) -> bool:
                d = 'Y/n' if default else 'y/N'
                r = input(f"{prompt} ({d}): ").strip().lower()
                if not r:
                    return default
                return r in ('y','yes')

            print('\nArtifact processing complete for:', url)
            print('Proposed next steps: assign event IDs, merge/fuse per-event, and generate reports.')
            if _yn('Run the service pipeline now (assign IDs, merge, generate reports)?', default=True):
                # gather options
                dry = _yn('Dry run (compute only, do not write outputs)?', default=True)
                clear = _yn('Clear caches before compute?', default=False)
                run_assign = _yn('Assign event IDs?', default=True)
                run_merge = _yn('Merge events (enriched/fused)?', default=True)
                run_reports = _yn('Generate reports?', default=False)
                report_eid = None
                report_aud = args.audience
                report_family = args.family_sensitive
                if run_reports:
                    eid_in = input('Target event_id (leave empty for all): ').strip()
                    if eid_in:
                        report_eid = eid_in
                    aud_in = input(f"Audience [climbers/general] (default: {args.audience}): ").strip().lower()
                    if aud_in in ('climbers','general'):
                        report_aud = aud_in
                    if _yn('Family-sensitive tone?', default=args.family_sensitive):
                        report_family = True

                ts_print('[INFO] Running selected service pipeline steps...')
                if run_assign:
                    stats = _assign_event_ids(dry_run=dry, cache_clear=clear)
                    ts_print(f"[service] event_id assignment: files={stats.get('files',0)} clusters={stats.get('clusters',0)} written={stats.get('written',0)}{' (dry-run)' if dry else ''}")
                if run_merge:
                    stats = _merge_and_fuse(dry_run=dry, cache_clear=clear)
                    ts_print(f"[service] merge+fusion: events={stats.get('events',0)} enriched={stats.get('enriched',0)} fused={stats.get('fused',0)}{' (dry-run)' if dry else ''}")
                    ts_print('[note] Fused outputs are canonical: events/fused/{event_id}.json')
                if run_reports:
                    from pathlib import Path as _P
                    fused_dir = _P('events') / 'fused'
                    if report_eid:
                        targets = [report_eid]
                    else:
                        targets = [p.stem for p in fused_dir.glob('*.json')]
                    wrote = 0
                    for eid in targets:
                        pth = _generate_report(eid, audience=report_aud, family_sensitive=report_family, dry_run=dry)
                        if pth:
                            wrote += 1
                            ts_print(f"[report] wrote {pth}")
                    ts_print(f"[service] reports: {wrote}/{len(targets)} written{' (dry-run)' if dry else ''}")

    # Run service pipeline actions if requested
    if args.assign_event_ids or args.merge_events or args.generate_reports:
        ts_print("[INFO] Service pipeline starting...")
        # 1) Assign event IDs
        if args.assign_event_ids:
            stats = _assign_event_ids(dry_run=args.dry_run, cache_clear=args.cache_clear)
            ts_print(f"[service] event_id assignment: files={stats.get('files',0)} clusters={stats.get('clusters',0)} written={stats.get('written',0)}{' (dry-run)' if args.dry_run else ''}")
        # 2) Merge and fuse
        if args.merge_events:
            stats = _merge_and_fuse(dry_run=args.dry_run, cache_clear=args.cache_clear)
            ts_print(f"[service] merge+fusion: events={stats.get('events',0)} enriched={stats.get('enriched',0)} fused={stats.get('fused',0)}{' (dry-run)' if args.dry_run else ''}")
            ts_print("[note] Fused outputs are canonical: events/fused/{event_id}.json")
        # 3) Reports
        if args.generate_reports:
            from pathlib import Path as _P
            fused_dir = _P('events') / 'fused'
            if args.event_id:
                targets = [args.event_id]
            else:
                targets = [p.stem for p in fused_dir.glob('*.json')]
            wrote = 0
            for eid in targets:
                pth = _generate_report(eid, audience=args.audience, family_sensitive=args.family_sensitive, dry_run=args.dry_run)
                if pth:
                    wrote += 1
                    ts_print(f"[report] wrote {pth}")
            ts_print(f"[service] reports: {wrote}/{len(targets)} written{' (dry-run)' if args.dry_run else ''}")
