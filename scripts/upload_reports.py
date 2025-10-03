#!/usr/bin/env python3
"""Uploads generated markdown reports to a GCS bucket."""

import argparse
import logging
import os
from pathlib import Path

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False


logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / 'events' / 'reports'


def upload_reports(bucket_name: str, dry_run: bool = False):
    """Uploads all .md files from the local reports dir to a GCS bucket."""
    if not GCS_AVAILABLE:
        logger.error("google-cloud-storage is not installed. Please run: pip install google-cloud-storage")
        return

    if not bucket_name:
        logger.error("GCS_BUCKET name must be provided.")
        return

    if not REPORTS_DIR.exists() or not any(REPORTS_DIR.iterdir()):
        logger.warning(f"Reports directory is empty or does not exist: {REPORTS_DIR}")
        return

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    logger.info(f"Uploading reports to gs://{bucket_name}/reports/ ...")

    uploaded_count = 0
    for report_file in REPORTS_DIR.glob('*.md'):
        blob_name = f"reports/{report_file.name}"
        logger.info(f"-> Uploading {report_file.name} to {blob_name}")
        if not dry_run:
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(report_file))
        uploaded_count += 1

    logger.info(f"✅ Upload complete. {uploaded_count} reports {'would be' if dry_run else ''} uploaded.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Upload generated reports to GCS.")
    parser.add_argument(
        '--bucket',
        help="GCS bucket name. Defaults to GCS_BUCKET env var.",
        default=os.environ.get('GCS_BUCKET', 'accident-reports-artifacts')
    )
    parser.add_argument('--dry-run', action='store_true', help="Show what would be uploaded without uploading.")
    args = parser.parse_args()

    upload_reports(bucket_name=args.bucket, dry_run=args.dry_run)