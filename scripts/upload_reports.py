#!/usr/bin/env python3
"""Uploads generated markdown reports to a GCS bucket."""

import argparse
import logging
import os
from pathlib import Path

try:
    from google.cloud import storage
    GCS_CLIENT_AVAILABLE = True
except ImportError:
    GCS_CLIENT_AVAILABLE = False

import shutil
import subprocess
GCS_UTIL_AVAILABLE = shutil.which('gsutil') is not None


logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / 'events' / 'reports'


def _upload_with_client(bucket_name: str, files, dry_run: bool = False):
    if not GCS_CLIENT_AVAILABLE:
        raise RuntimeError('google-cloud-storage client not available')

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    logger.info(f"Uploading reports to gs://{bucket_name}/reports/ using client library...")

    uploaded_count = 0
    for report_file in files:
        blob_name = f"reports/{report_file.name}"
        logger.info(f"-> Uploading {report_file.name} to {blob_name}")
        if not dry_run:
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(report_file))
        uploaded_count += 1

    return uploaded_count


def _upload_with_gsutil(bucket_name: str, files, dry_run: bool = False):
    if not GCS_UTIL_AVAILABLE:
        raise RuntimeError('gsutil not available in PATH')

    logger.info(f"Uploading reports to gs://{bucket_name}/reports/ using gsutil...")
    uploaded_count = 0
    for report_file in files:
        dest = f'gs://{bucket_name}/reports/{report_file.name}'
        logger.info(f"-> Copying {report_file} -> {dest}")
        if not dry_run:
            subprocess.check_call(['gsutil', 'cp', str(report_file), dest])
        uploaded_count += 1

    return uploaded_count


def upload_reports(bucket_name: str, dry_run: bool = False, method: str = 'auto'):
    """Uploads all .md files from the local reports dir to a GCS bucket.

    method: one of 'auto' (choose client if available else gsutil), 'client', or 'gsutil'
    """
    if not bucket_name:
        logger.error("GCS_BUCKET name must be provided.")
        return

    if not REPORTS_DIR.exists() or not any(REPORTS_DIR.glob('*.md')):
        logger.warning(f"Reports directory is empty or does not exist: {REPORTS_DIR}")
        return

    files = sorted(REPORTS_DIR.glob('*.md'))

    # Decide which method to use
    chosen = method
    if method == 'auto':
        if GCS_CLIENT_AVAILABLE:
            chosen = 'client'
        elif GCS_UTIL_AVAILABLE:
            chosen = 'gsutil'
        else:
            logger.error('No upload methods available: install google-cloud-storage or ensure gsutil is on PATH')
            return

    try:
        if chosen == 'client':
            count = _upload_with_client(bucket_name, files, dry_run=dry_run)
        elif chosen == 'gsutil':
            count = _upload_with_gsutil(bucket_name, files, dry_run=dry_run)
        else:
            logger.error(f"Unknown upload method: {method}")
            return

        logger.info(f"✅ Upload complete. {count} reports {'would be' if dry_run else ''} uploaded.")
    except Exception as e:
        logger.exception(f"Upload failed using method={chosen}: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Upload generated reports to GCS.")
    parser.add_argument(
        '--bucket',
        help="GCS bucket name. Defaults to GCS_BUCKET env var.",
        default=os.environ.get('GCS_BUCKET', 'accident-reports-artifacts')
    )
    parser.add_argument('--dry-run', action='store_true', help="Show what would be uploaded without uploading.")
    parser.add_argument('--method', choices=['auto', 'client', 'gsutil'], default='auto',
                        help="Upload method to use: 'auto' (default), 'client' (google-cloud-storage), or 'gsutil'")
    args = parser.parse_args()

    upload_reports(bucket_name=args.bucket, dry_run=args.dry_run, method=args.method)