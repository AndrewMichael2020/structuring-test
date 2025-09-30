#!/usr/bin/env python3
"""Import existing artifacts JSON files under artifacts/ into the TinyDB store.

Usage:
  python scripts/import_artifacts_to_db.py --artifacts-dir artifacts --db-path artifacts_db.json [--dry-run] [--skip-existing]
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store_artifacts import init_db, upsert_artifact, query_artifacts, close_db
try:
    from tqdm import tqdm
except Exception:
    tqdm = None


def find_artifacts(base: Path):
    for domain in base.iterdir():
        if not domain.is_dir():
            continue
        for run in domain.iterdir():
            if not run.is_dir():
                continue
            p = run / 'accident_info.json'
            if p.exists():
                yield p


def main():
    import threading
    import queue
    import pickle

    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir', default='artifacts')
    parser.add_argument('--db-path', default='artifacts_db.json')
    parser.add_argument('--backend', default=None, choices=['sqlite', 'tinydb', 'memory'], help='Optional backend to use for storing artifacts')
    parser.add_argument('--log-file', default=None, help='Optional file to append logs to')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker threads to read files in parallel (DB writes remain single-threaded)')
    parser.add_argument('--batch-size', type=int, default=1, help='Number of artifacts to write per DB transaction (default: 1)')
    parser.add_argument('--resume', action='store_true', help='Skip files already processed in previous runs (tracked by --state-file)')
    parser.add_argument('--state-file', default='.import_state.pkl', help='Path to state file for resume mode (default: .import_state.pkl)')
    args = parser.parse_args()

    q_writer = queue.Queue(maxsize=2*args.batch_size if args.batch_size > 1 else 10)
    writer_done = threading.Event()
    writer_exception = []

    def _write_batch(batch):
        nonlocal imported, processed_urls
        for p, j in batch:
            src = j.get('source_url')
            if args.dry_run:
                msg = f'[DRY] Would import {p}'
                print(msg)
                if args.log_file:
                    Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.log_file).write_text(msg + "\n", encoding='utf-8')
                imported += 1
                if args.resume and src:
                    processed_urls.add(src)
                continue
            try:
                upsert_artifact(j)
                imported += 1
                if args.resume and src:
                    processed_urls.add(src)
            except Exception as e:
                print(f'Failed to import {p}: {e}')
                if args.log_file:
                    Path(args.log_file).write_text(f'Failed to import {p}: {e}\n', encoding='utf-8')
        # persist resume state after each batch
        if args.resume and processed_urls:
            try:
                with open(args.state_file, 'wb') as f:
                    pickle.dump(processed_urls, f)
            except Exception:
                pass

    def writer_thread():
        nonlocal imported, skipped, processed_urls
        batch = []
        while True:
            item = q_writer.get()
            if item is None:
                break
            p, j, skip_reason = item
            if skip_reason:
                skipped += 1
                continue
            batch.append((p, j))
            if len(batch) >= args.batch_size:
                _write_batch(batch)
                batch = []
        if batch:
            _write_batch(batch)
        writer_done.set()

    writer = threading.Thread(target=writer_thread, daemon=True)
    writer.start()
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir', default='artifacts')
    parser.add_argument('--db-path', default='artifacts_db.json')
    parser.add_argument('--backend', default=None, choices=['sqlite', 'tinydb', 'memory'], help='Optional backend to use for storing artifacts')
    parser.add_argument('--log-file', default=None, help='Optional file to append logs to')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker threads to read files in parallel (DB writes remain single-threaded)')
    parser.add_argument('--batch-size', type=int, default=1, help='Number of artifacts to write per DB transaction (default: 1)')
    parser.add_argument('--resume', action='store_true', help='Skip files already processed in previous runs (tracked by --state-file)')
    parser.add_argument('--state-file', default='.import_state.pkl', help='Path to state file for resume mode (default: .import_state.pkl)')
    args = parser.parse_args()

    base = Path(args.artifacts_dir)
    if not base.exists():
        print(f'Artifacts dir not found: {base}')
        return

    # Only initialize DB when actually importing (avoid creating DB file on --dry-run)
    db_inited = False
    imported = 0
    skipped = 0
    if not args.dry_run:
        init_db(args.db_path, backend=args.backend)
        db_inited = True
    artifacts = list(find_artifacts(base))
    imported = 0
    skipped = 0

    # Resume mode: load processed source_urls from state file
    processed_urls = set()
    if args.resume and Path(args.state_file).exists():
        import pickle
        try:
            with open(args.state_file, 'rb') as f:
                processed_urls = pickle.load(f)
        except Exception:
            processed_urls = set()

    # Prepare resume state
    state_path = Path(args.state_file)
    processed = set()
    if args.resume and state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding='utf-8'))
            processed = set(data.get('processed', [])) if isinstance(data, dict) else set(data)
        except Exception:
            processed = set()

    # Worker pool to read and parse files in parallel; DB writes handled by writer thread
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from queue import Queue, Empty
    import threading

    def read_json(path: Path):
        try:
            return path, json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            return path, e

    use_tqdm = (tqdm is not None)
    q = Queue()

    def writer_thread_fn():
        """Consume parsed artifacts from queue and write them in batches."""
        nonlocal processed
        batch = []
        running = True
        while running:
            try:
                item = q.get(timeout=1.0)
            except Empty:
                item = None
            if item is None:
                # timeout or sentinel; flush batch on shutdown condition
                if batch:
                    _write_batch(batch)
                    batch = []
                # check whether main thread signaled completion by putting a sentinel object
                # we'll detect sentinel via a special object placed below
                continue
            if item is SENTINEL:
                # flush remaining and exit
                if batch:
                    _write_batch(batch)
                break
            batch.append(item)
            if len(batch) >= args.batch_size:
                _write_batch(batch)
                batch = []

    def _write_batch(items):
        """Write a batch of parsed artifact dicts to the DB.
        For sqlite backend use executemany for speed; otherwise call upsert_artifact.
        After successful write, update the processed set and persist state if requested.
        """
        nonlocal processed
        if args.dry_run:
            for p, j in items:
                msg = f'[DRY] Would import {p}'
                print(msg)
                if args.log_file:
                    Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.log_file).write_text(msg + "\n", encoding='utf-8')
            return

        # ensure DB initialized
        if not db_inited:
            init_db(args.db_path, backend=args.backend)
        try:
            if args.backend == 'sqlite' or (args.backend is None and True):
                # attempt sqlite optimized path; fall back to upsert_artifact on failure
                try:
                    import sqlite3 as _sqlite3
                    conn = _sqlite3.connect(str(args.db_path))
                    cur = conn.cursor()
                    rows = []
                    for p, j in items:
                        src = j.get('source_url')
                        rec = (
                            src,
                            j.get('source_url', '').split('/')[2] if '/' in j.get('source_url', '') else j.get('source_url'),
                            j.get('extracted_at'),
                            j.get('mountain_name'),
                            j.get('num_fatalities'),
                            j.get('extraction_confidence_score'),
                            json.dumps(j),
                        )
                        rows.append(rec)
                    cur.executemany(
                        """INSERT OR REPLACE INTO artifacts
                        (source_url, domain, ts, mountain_name, num_fatalities, extraction_confidence_score, artifact_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    # fallback to safer per-item upsert
                    for p, j in items:
                        upsert_artifact(j)
            else:
                for p, j in items:
                    upsert_artifact(j)
        except Exception as e:
            for p, j in items:
                print(f'Failed to import batch item {p}: {e}')
                if args.log_file:
                    Path(args.log_file).write_text(f'Failed to import batch item {p}: {e}\n', encoding='utf-8')
            return

        # mark processed and persist state
        for p, j in items:
            src = j.get('source_url')
            if src:
                processed.add(src)
        if args.state_file:
            try:
                state_path.write_text(json.dumps({'processed': list(processed)}), encoding='utf-8')
            except Exception:
                pass

    # Sentinel object to signal writer shutdown
    SENTINEL = object()

    writer = threading.Thread(target=writer_thread_fn, daemon=True)
    writer.start()

    if args.workers and args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(read_json, p) for p in artifacts]
            iterator = as_completed(futures)
            if use_tqdm:
                iterator = tqdm(iterator, total=len(futures), desc='artifacts')
            for fut in iterator:
                p, result = fut.result()
                if isinstance(result, Exception):
                    print(f'Failed to read {p}: {result}')
                    continue
                j = result
                src = j.get('source_url')
                # resume/skip checks
                if args.resume and src in processed:
                    skipped += 1
                    continue
                if args.skip_existing and src:
                    if not db_inited:
                        init_db(args.db_path, backend=args.backend)
                        db_inited = True
                    exists = query_artifacts({'source_url': src})
                    if exists:
                        skipped += 1
                        continue
                # enqueue for writer
                q.put((p, j))
    else:
        # single-threaded path (workers=1)
        iter_source = artifacts
        if use_tqdm:
            iter_source = tqdm(artifacts, desc='artifacts')
        for p in iter_source:
            try:
                j = json.loads(p.read_text(encoding='utf-8'))
            except Exception as e:
                print(f'Failed to read {p}: {e}')
                continue
            src = j.get('source_url')
            if args.resume and src in processed:
                skipped += 1
                continue
            if args.skip_existing and src:
                # If user requested skipping existing, we need DB to check. Initialize if needed.
                if not db_inited:
                    init_db(args.db_path, backend=args.backend)
                    db_inited = True
                exists = query_artifacts({'source_url': src})
                if exists:
                    skipped += 1
                    continue
            # enqueue for writer
            q.put((p, j))
    # signal writer to finish
    q.put(SENTINEL)
    writer.join()

    # imported count isn't tracked in batch writer; recompute from processed set size for summary
    print(f'Imported: {len(processed)}, skipped: {skipped}')
    close_db()


if __name__ == '__main__':
    main()
