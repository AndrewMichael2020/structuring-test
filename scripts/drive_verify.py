#!/usr/bin/env python3
"""Verify uploaded artifacts CSV on Google Drive.

Usage: set DRIVE_OAUTH_CLIENT_SECRETS and optionally DRIVE_FOLDER_ID in env, then run:
  python scripts/drive_verify.py

This will list files matching the configured DRIVE_ARTIFACTS_FILENAME (default artifacts.csv),
print metadata (id, webViewLink, parents) and download the file to show the CSV header.
"""
from pathlib import Path
import io
import csv
import os
import sys

try:
    from drive_storage import DriveStorage
except Exception as e:
    print("Failed to import DriveStorage:", e)
    sys.exit(2)

from googleapiclient.http import MediaIoBaseDownload


def main():
    name = os.environ.get('DRIVE_ARTIFACTS_FILENAME', 'artifacts.csv')
    print(f"Looking for Drive file named: {name}")
    try:
        ds = DriveStorage.from_env()
    except Exception as e:
        print("Failed to initialize DriveStorage.from_env():", e)
        print("Make sure DRIVE_OAUTH_CLIENT_SECRETS is set and you have a token.")
        sys.exit(1)

    service = ds.service
    folder = ds.folder_id

    q = f"name='{name}' and trashed=false"
    if folder:
        q += f" and '{folder}' in parents"

    try:
        res = service.files().list(q=q, fields="files(id,name,parents,webViewLink)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
    except Exception as e:
        print("Drive API list failed:", e)
        sys.exit(1)

    files = res.get('files', [])
    if not files:
        print("No files found matching that name (in folder if DRIVE_FOLDER_ID set). Try removing DRIVE_FOLDER_ID to search all Drive.)")
        # As a fallback, search without folder restriction
        if folder:
            print("Retrying search without folder restriction...")
            try:
                res2 = service.files().list(q=f"name='{name}' and trashed=false", fields="files(id,name,parents,webViewLink)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
                files = res2.get('files', [])
            except Exception as e:
                print("Fallback list failed:", e)
    if not files:
        print("Still no files found. Possible reasons:\n - OAuth account is different from the Drive you expect\n - File was uploaded to a Shared Drive or different folder\n - The upload failed silently. Check logs for [drive] messages.")
        sys.exit(0)

    print(f"Found {len(files)} file(s):")
    for f in files:
        fid = f.get('id')
        fname = f.get('name')
        parents = f.get('parents')
        link = f.get('webViewLink')
        print('-' * 40)
        print(f"id: {fid}\nname: {fname}\nlink: {link}\nparents: {parents}")

        # Attempt to download a small portion (CSV header) and show it
        try:
            request = service.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            data = fh.getvalue().decode('utf-8', errors='replace')
            # print first 2KB for safety
            snippet = data[:2048]
            print('\n--- file head (first 2KB) ---')
            print(snippet)
            # try to parse header row
            try:
                rdr = csv.reader(io.StringIO(snippet))
                header = next(rdr)
                print('\nCSV header columns:')
                for col in header:
                    print(' -', col)
            except Exception:
                print('\nCould not parse CSV header from snippet.')
        except Exception as e:
            print('Failed to download/inspect file:', e)


if __name__ == '__main__':
    main()
